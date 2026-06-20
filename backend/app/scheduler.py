"""APScheduler 调度器：定时配置同步（FR-2.2，默认 6h）+ 断连回补巡检（Sprint 2）
+ 防轰炸周期摘要（Sprint 4）+ 定时邮件报表（Sprint 6）。
"""
from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.constants import BACKFILL_GAP_THRESHOLD_S, NOTIFY_DIGEST_INTERVAL_S
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.metrics import M_BACKFILL_WATCH, M_CONFIG_SYNC, record_failure
from app.ems.connection import get_manager
from app.history.backfill import backfill_watch
from app.models.system import EmsConfig, ReportSchedule
from app.notify.dispatcher import flush_digests
from app.reports.service import run_report_schedule

logger = get_logger("sync")

_scheduler: AsyncIOScheduler | None = None

REPORT_JOB_PREFIX = "report_"


async def _scheduled_config_sync() -> None:
    manager = get_manager()
    if manager is None or not manager.client.token:
        logger.info("定时同步跳过：EMS 未连接")
        return
    try:
        await manager.manual_sync()
    except Exception as exc:
        logger.error("定时同步失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_CONFIG_SYNC, error=str(exc))


async def _scheduled_backfill_watch() -> None:
    """断连回补巡检：检测推送中断/恢复并触发回补（自身吞错，避免影响调度）。

    审查 S4：巡检自身失败此前仅记日志，其失效是「沉默的」（不再记录缺口→恢复后不回补）。
    此处补记指标，使巡检瘫痪可被 /health 与告警发现。
    """
    try:
        await backfill_watch()
    except Exception as exc:
        logger.error("回补巡检失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_BACKFILL_WATCH, error=str(exc))


async def _scheduled_flush_digests() -> None:
    """防轰炸周期摘要：把合并期内累计的告警汇总成摘要发送。"""
    try:
        await flush_digests()
    except Exception as exc:
        logger.error("摘要刷新失败", extra={"extra_fields": {"error": str(exc)}})


async def _run_report_job(schedule_id: int) -> None:
    """定时报表任务（自身吞错，避免影响调度）。"""
    try:
        await run_report_schedule(schedule_id)
    except Exception as exc:
        logger.error(
            "定时报表执行失败",
            extra={"extra_fields": {"schedule_id": schedule_id, "error": str(exc)}},
        )


async def reload_report_jobs() -> int:
    """根据 report_schedules 表重建全部报表 cron 任务（增删改后调用）。返回注册任务数。"""
    if _scheduler is None:
        return 0
    # 先移除现有报表任务
    for job in list(_scheduler.get_jobs()):
        if job.id.startswith(REPORT_JOB_PREFIX):
            _scheduler.remove_job(job.id)
    # 再按启用计划重建
    count = 0
    async with AsyncSessionLocal() as db:
        schedules = (
            await db.execute(select(ReportSchedule).where(ReportSchedule.enabled.is_(True)))
        ).scalars().all()
    for sched in schedules:
        try:
            trigger = CronTrigger.from_crontab(sched.cron, timezone=settings.timezone)
        except ValueError as exc:
            logger.error(
                "报表 cron 表达式非法，跳过",
                extra={"extra_fields": {"schedule_id": sched.id, "cron": sched.cron,
                                        "error": str(exc)}},
            )
            continue
        _scheduler.add_job(
            _run_report_job,
            trigger,
            args=[sched.id],
            id=f"{REPORT_JOB_PREFIX}{sched.id}",
            max_instances=1,
            coalesce=True,
        )
        count += 1
    logger.info("报表定时任务已重建", extra={"extra_fields": {"count": count}})
    return count


def report_next_runs() -> dict[int, datetime]:
    """读取已注册报表任务的下次触发时间，键为 schedule_id。"""
    out: dict[int, datetime] = {}
    if _scheduler is None:
        return out
    for job in _scheduler.get_jobs():
        if job.id.startswith(REPORT_JOB_PREFIX) and job.next_run_time is not None:
            try:
                sid = int(job.id[len(REPORT_JOB_PREFIX):])
            except ValueError:
                continue
            out[sid] = job.next_run_time
    return out


async def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    interval = 21600
    async with AsyncSessionLocal() as db:
        cfg = await db.get(EmsConfig, 1)
        if cfg is not None:
            interval = cfg.sync_interval_s
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _scheduled_config_sync,
        "interval",
        seconds=interval,
        id="config_sync",
        max_instances=1,
        coalesce=True,
    )
    # 断连回补巡检：周期略小于缺口阈值，确保中断/恢复能被及时捕捉
    watch_interval = max(15, BACKFILL_GAP_THRESHOLD_S // 2)
    _scheduler.add_job(
        _scheduled_backfill_watch,
        "interval",
        seconds=watch_interval,
        id="backfill_watch",
        max_instances=1,
        coalesce=True,
    )
    # 防轰炸周期摘要
    _scheduler.add_job(
        _scheduled_flush_digests,
        "interval",
        seconds=NOTIFY_DIGEST_INTERVAL_S,
        id="flush_digests",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    # 注册定时邮件报表（依据 report_schedules 表）
    report_jobs = await reload_report_jobs()
    logger.info(
        "调度器已启动",
        extra={"extra_fields": {
            "config_sync_interval_s": interval,
            "backfill_watch_interval_s": watch_interval,
            "digest_interval_s": NOTIFY_DIGEST_INTERVAL_S,
            "report_jobs": report_jobs,
        }},
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
