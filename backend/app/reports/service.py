"""报表编排：周期计算、正文渲染、定时报表生成与邮件分发。

纯函数 `period_for` / `render_report_text` 可离线单测；
`run_report_schedule` 在调度触发时执行：取计划 → 解析接收组邮箱 → 生成统计 + CSV 附件 → 发邮件。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.notify import NotifyChannel, Recipient, RecipientGroupMember
from app.models.system import ReportSchedule
from app.reports.export import build_csv, load_alarm_rows
from app.reports.mailer import MailerError, send_report_mail
from app.reports.stats import StatsResult, load_alarm_stats

logger = get_logger("report")

# 报表类型 → 统计粒度
TYPE_GRANULARITY = {"daily": "day", "weekly": "week", "monthly": "month"}
TYPE_LABEL = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
LEVEL_NAME = {1: "紧急", 2: "严重", 3: "重要", 4: "次要", 5: "提示"}
SOURCE_LABEL = {"platform": "平台规则", "ems": "EMS设备"}


def _day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def period_for(report_type: str, now: datetime) -> tuple[int, int]:
    """返回 now 之前「已完成」周期的 [start, end] Unix 秒（含本地时区语义）。

    - daily：昨天 00:00 → 今天 00:00
    - weekly：上一 ISO 周（周一~周日）
    - monthly：上一自然月
    """
    today = _day_start(now)
    if report_type == "daily":
        start = today - timedelta(days=1)
        end = today
    elif report_type == "weekly":
        this_week_mon = today - timedelta(days=today.weekday())
        start = this_week_mon - timedelta(days=7)
        end = this_week_mon
    elif report_type == "monthly":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        start = last_prev.replace(day=1)
        end = first_this
    else:
        raise ValueError(f"未知报表类型: {report_type}")
    # end 取闭区间末尾（减 1 秒），避免与下一周期边界重叠
    return int(start.timestamp()), int(end.timestamp()) - 1


def render_report_text(
    stats: StatsResult, names: dict[str, str], report_type: str, tz: ZoneInfo
) -> str:
    """渲染纯文本报表正文。"""
    label = TYPE_LABEL.get(report_type, "报表")
    start_s = datetime.fromtimestamp(stats.start, tz=tz).strftime("%Y-%m-%d %H:%M")
    end_s = datetime.fromtimestamp(stats.end, tz=tz).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"动环监控预警平台 — 告警{label}",
        f"统计区间：{start_s} ~ {end_s}（{settings.timezone}）",
        "",
        f"告警总数：{stats.total}",
        "",
        "按级别：",
    ]
    for lv in (1, 2, 3, 4, 5):
        lines.append(f"  - {LEVEL_NAME[lv]}：{stats.by_level.get(lv, 0)}")
    lines.append("")
    lines.append("按来源：")
    for src, cnt in sorted(stats.by_source.items()):
        lines.append(f"  - {SOURCE_LABEL.get(src, src)}：{cnt}")
    lines.append("")
    if stats.mtta_seconds is not None:
        lines.append(f"平均受理时长(MTTA)：{stats.mtta_seconds / 60:.1f} 分钟")
    if stats.mttr_seconds is not None:
        lines.append(f"平均恢复时长(MTTR)：{stats.mttr_seconds / 60:.1f} 分钟")
    lines.append("")
    lines.append(f"Top 告警资源（前 {len(stats.top_resources)}）：")
    for rid, cnt in stats.top_resources:
        nm = names.get(rid, "")
        lines.append(f"  - {nm or rid}（{rid}）：{cnt} 次")
    lines.append("")
    lines.append("详细告警明细见附件 CSV。")
    return "\n".join(lines)


async def _group_emails(db: AsyncSession, group_ids: list[int]) -> list[str]:
    if not group_ids:
        return []
    rows = (
        await db.execute(
            select(Recipient.email)
            .join(RecipientGroupMember, RecipientGroupMember.recipient_id == Recipient.id)
            .where(
                RecipientGroupMember.group_id.in_(group_ids),
                Recipient.enabled.is_(True),
                Recipient.email.isnot(None),
            )
            .distinct()
        )
    ).scalars().all()
    return [e for e in rows if e]


async def _email_channel_configs(db: AsyncSession) -> list[dict[str, object]]:
    """取全部启用的邮件渠道 SMTP 配置（原始 config，密码加密态），按 id 升序。

    返回列表而非单条：发送时按序逐个尝试，遇坏渠道自动切换到下一个，
    避免单个失效渠道阻塞整个报表分发。
    """
    rows = (
        await db.execute(
            select(NotifyChannel)
            .where(NotifyChannel.type == "email", NotifyChannel.enabled.is_(True))
            .order_by(NotifyChannel.id)
        )
    ).scalars().all()
    return [dict(c.config or {}) for c in rows]


async def run_report_schedule(schedule_id: int) -> dict[str, object]:
    """执行一个报表计划：生成统计 + CSV 附件并发邮件。返回执行摘要。"""
    tz = ZoneInfo(settings.timezone)
    async with AsyncSessionLocal() as db:
        sched = await db.get(ReportSchedule, schedule_id)
        if sched is None:
            raise ValueError(f"报表计划不存在: {schedule_id}")
        granularity = TYPE_GRANULARITY.get(sched.report_type)
        if granularity is None:
            raise ValueError(f"未知报表类型: {sched.report_type}")

        start, end = period_for(sched.report_type, datetime.now(tz))
        stats, names = await load_alarm_stats(db, start, end, granularity)
        headers, alarm_rows = await load_alarm_rows(db, start, end)
        csv_bytes = build_csv(headers, alarm_rows)
        body = render_report_text(stats, names, sched.report_type, tz)
        label = TYPE_LABEL.get(sched.report_type, "报表")
        date_tag = datetime.fromtimestamp(start, tz=tz).strftime("%Y%m%d")
        subject = f"[动环监控] 告警{label} {date_tag}（共 {stats.total} 条）"
        filename = f"alarm_{sched.report_type}_{date_tag}.csv"

        emails = await _group_emails(db, sched.group_ids or [])
        configs = await _email_channel_configs(db)

        if not emails:
            logger.warning(
                "报表计划无有效收件人，跳过发送",
                extra={"extra_fields": {"schedule_id": schedule_id}},
            )
            return {"schedule_id": schedule_id, "sent": False, "reason": "无有效收件人",
                    "total": stats.total}
        if not configs:
            logger.warning(
                "无启用的邮件渠道，报表无法发送",
                extra={"extra_fields": {"schedule_id": schedule_id}},
            )
            return {"schedule_id": schedule_id, "sent": False, "reason": "无启用邮件渠道",
                    "total": stats.total}

        # 逐个邮件渠道尝试，首个成功即停；全部失败则返回最后错误
        last_err = ""
        for idx, config in enumerate(configs):
            try:
                await send_report_mail(config, emails, subject, body, [(filename, csv_bytes)])
            except MailerError as exc:
                last_err = str(exc)
                logger.warning(
                    "报表邮件渠道发送失败，尝试下一个",
                    extra={"extra_fields": {"schedule_id": schedule_id, "channel_idx": idx,
                                            "error": last_err}},
                )
                continue
            logger.info(
                "报表邮件已发送",
                extra={"extra_fields": {
                    "schedule_id": schedule_id, "report_type": sched.report_type,
                    "recipients": len(emails), "total": stats.total, "channel_idx": idx,
                }},
            )
            return {"schedule_id": schedule_id, "sent": True, "recipients": len(emails),
                    "total": stats.total, "subject": subject}

        logger.error(
            "报表邮件全部渠道发送失败",
            extra={"extra_fields": {"schedule_id": schedule_id, "error": last_err}},
        )
        return {"schedule_id": schedule_id, "sent": False, "reason": last_err,
                "total": stats.total}
