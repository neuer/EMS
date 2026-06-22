"""断连回补：检测推送中断 → 恢复后用 offline_value 补齐缺口。

红线 #5（严格遵守）：
- 单次 offline_value ≤100 测点（chunk_points）。
- 单次跨度 ≤1 天（slice_time_range）。
- 同一时间仅一个历史请求在跑：Redis 锁 lock:history 串行。
- 回补按测点分批 + 按时间分片 + 串行执行。

回补落原始层 point_history（幂等 upsert）并刷新 5min 连续聚合（写降采样层，红线 #6），
同时写 sync_log(kind=backfill) 作为缺口标记。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    BACKFILL_GAP_THRESHOLD_S,
    BACKFILL_INTERVAL,
    BACKFILL_MAX_WINDOW_S,
    OFFLINE_MAX_POINTS,
    OFFLINE_MAX_SPAN_S,
    REDIS_BACKFILL_GAP_START,
    REDIS_EMS_CONN,
    REDIS_HISTORY_LOCK,
    REDIS_HISTORY_LOCK_TTL,
    REDIS_INGEST_LAST_TS,
)
from app.core.db import AsyncSessionLocal, engine
from app.core.logging import get_logger
from app.core.metrics import (
    M_BACKFILL_SLICE,
    M_BACKFILL_WATCH,
    M_CAGG_REFRESH,
    record_failure,
)
from app.core.redis import redis_client, release_lock_if_owner
from app.ems.client import EmsClient
from app.ems.protocol import EmsError
from app.models.asset import Point
from app.models.system import SyncLog

logger = get_logger("history")


# ---- 纯函数：分批 / 分片（红线 #5，可离线单测）----
def chunk_points(ids: list[str], size: int = OFFLINE_MAX_POINTS) -> list[list[str]]:
    """测点去重保序后按 size（≤100）分批。"""
    seen: set[str] = set()
    uniq: list[str] = []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            uniq.append(i)
    return [uniq[i : i + size] for i in range(0, len(uniq), size)]


def slice_time_range(
    start: int, end: int, max_span: int = OFFLINE_MAX_SPAN_S
) -> list[tuple[int, int]]:
    """把 [start,end] 切成每段跨度 ≤max_span（≤1 天）的连续分片。"""
    if end <= start:
        return []
    slices: list[tuple[int, int]] = []
    s = start
    while s < end:
        e = min(s + max_span, end)
        slices.append((s, e))
        s = e
    return slices


@dataclass
class BackfillResult:
    points: int = 0  # 写入样本数
    batches: int = 0  # offline_value 成功调用次数
    failed_slices: int = 0  # 可重试失败的分片数（传输/超时）；>0 时不应清缺口
    skipped: bool = False
    reason: str = ""


def _utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# 与采集层一致的幂等 upsert（回补可能与实时落库交叉，ON CONFLICT 保证幂等）
_INSERT_HISTORY = text(
    "INSERT INTO point_history (point_id, ts, value) VALUES (:point_id, :ts, :value) "
    "ON CONFLICT (point_id, ts) DO UPDATE SET value = EXCLUDED.value"
)


def _flatten(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """offline_value 返回 [{resource_id,data_list:[{value,time}]}] → point_history 行。"""
    rows: list[dict[str, Any]] = []
    for item in series:
        pid = item.get("resource_id")
        if not pid:
            continue
        for dp in item.get("data_list") or []:
            t = _to_int(dp.get("time"))
            if t is None:
                continue
            rows.append({"point_id": pid, "ts": _utc(t), "value": _to_float(dp.get("value"))})
    return rows


async def _persist_raw(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    await db.execute(_INSERT_HISTORY, rows)
    return len(rows)


async def _refresh_cagg(start: int, end: int) -> None:
    """刷新 5min 连续聚合覆盖回补窗口（写降采样层）。

    refresh_continuous_aggregate 不可在事务块内执行，使用 AUTOCOMMIT 连接。
    末尾扩一个桶，确保边界桶被物化；失败不阻断（聚合策略会兜底）。
    """
    try:
        async with engine.connect() as conn:
            auto = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await auto.execute(
                text(
                    "CALL refresh_continuous_aggregate('point_history_5min', :s, :e)"
                ),
                {"s": _utc(start), "e": _utc(end + 600)},
            )
    except Exception as exc:
        # 审查 M8：物化失败仅 warning 而无指标时，降采样层可能长期缺数而无人知。补指标使其
        # 可被 /health 聚合（仍不阻断，聚合策略会兜底）。
        logger.warning("刷新 5min 连续聚合失败（将由聚合策略兜底）",
                       extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_CAGG_REFRESH, error=str(exc))


async def run_backfill(
    client: EmsClient,
    point_ids: list[str],
    start: int,
    end: int,
    *,
    detail: str = "断连回补",
) -> BackfillResult:
    """执行一次回补。串行获取 lock:history，分批分片调用 offline_value。"""
    if not point_ids or end <= start:
        return BackfillResult(skipped=True, reason="empty")

    # 红线 #5：串行锁，确保同一时间仅一个历史请求。锁值用唯一 token，释放时比对（审查 B1）。
    lock_token = uuid.uuid4().hex
    acquired = await redis_client.set(
        REDIS_HISTORY_LOCK, lock_token, nx=True, ex=REDIS_HISTORY_LOCK_TTL
    )
    if not acquired:
        logger.info("已有历史请求在跑，跳过本轮回补")
        return BackfillResult(skipped=True, reason="locked")

    result = BackfillResult()
    async with AsyncSessionLocal() as db:
        log = SyncLog(kind="backfill")
        db.add(log)
        await db.flush()
        try:
            batches = chunk_points(point_ids)
            slices = slice_time_range(start, end)
            for batch in batches:  # 按测点分批 ≤100
                for s, e in slices:  # 按时间分片 ≤1 天
                    # 审查 B1：持锁者在每个分片前续租 TTL，防止长回补中途锁过期被他人抢占。
                    await redis_client.expire(REDIS_HISTORY_LOCK, REDIS_HISTORY_LOCK_TTL)
                    try:
                        series = await client.offline_value(s, e, batch, BACKFILL_INTERVAL)
                    except EmsError as exc:
                        # 业务错误（如 101 批内含不存在 ID）：该分片不可恢复，跳过且**不**计为
                        # 可重试失败——否则一个坏测点会让整段缺口永远无法清除（审查 I1）。
                        logger.warning(
                            "offline_value 业务错误，跳过该分片",
                            extra={"extra_fields": {
                                "code": exc.code, "msg": exc.msg,
                                "points": len(batch), "start": s, "end": e,
                            }},
                        )
                        await record_failure(M_BACKFILL_SLICE, error=f"EmsError {exc.code}")
                        continue
                    except Exception as exc:
                        # 传输/超时等（含 EmsTransportError）：可重试。计入 failed_slices，使缺口被
                        # 保留，下轮重补，避免「整段缺口因一次网络抖动而永久丢失」（审查 I1）。
                        logger.warning(
                            "offline_value 传输失败，保留缺口待重试",
                            extra={"extra_fields": {
                                "points": len(batch), "start": s, "end": e, "error": str(exc),
                            }},
                        )
                        result.failed_slices += 1
                        await record_failure(M_BACKFILL_SLICE, error=str(exc))
                        continue
                    result.batches += 1
                    result.points += await _persist_raw(db, _flatten(series))
            await db.commit()

            # 写降采样层：刷新连续聚合覆盖回补窗口
            await _refresh_cagg(start, end)

            log.finished_at = datetime.now(UTC)
            log.added = result.points
            # 仅当无可重试失败时才算成功；部分失败必须可被监控发现（审查 I1）
            log.success = result.failed_slices == 0
            log.detail = (
                f"{detail} 窗口[{start},{end}] 测点={len(point_ids)} "
                f"调用={result.batches} 样本={result.points} 失败分片={result.failed_slices}"
            )
            await db.commit()
            logger.info(
                "断连回补完成",
                extra={"extra_fields": {
                    "start": start, "end": end, "points": len(point_ids),
                    "calls": result.batches, "samples": result.points,
                }},
            )
        except Exception as exc:
            # 审查 I1：失败可能源自落库 flush，会话已进入 pending-rollback；在污染会话上二次
            # commit 会抛错覆盖真实异常、失败日志也写不进。先回滚，再用独立会话写失败 SyncLog。
            await db.rollback()
            logger.error("断连回补失败", extra={"extra_fields": {"error": str(exc)}})
            async with AsyncSessionLocal() as log_db:
                log_db.add(SyncLog(
                    kind="backfill",
                    finished_at=datetime.now(UTC),
                    success=False,
                    detail=f"回补失败: {exc}",
                ))
                await log_db.commit()
            raise
        finally:
            await release_lock_if_owner(REDIS_HISTORY_LOCK, lock_token)
    return result


async def _active_point_ids() -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Point.resource_id).where(Point.is_active.is_(True))
        )
        return list(rows.scalars().all())


async def backfill_watch() -> None:
    """巡检：检测推送中断与恢复，恢复时触发回补（供调度器周期调用）。

    - 推送静默 > 阈值：冻结缺口起点（最后有效数据时刻），仅记录一次。
    - 推送恢复且存在缺口：用 offline_value 回补 [缺口起点, 最新数据时刻]。
    需 EMS 在线（持有 token）方可回补，否则等重连后再补。
    """
    from app.ems.connection import get_manager

    now = int(time.time())
    conn_state = await redis_client.hgetall(REDIS_EMS_CONN)
    last_push = _to_int(conn_state.get("last_push")) or 0
    if not last_push:
        return  # 尚未收到任何推送，无基线
    last_ts = _to_int(await redis_client.get(REDIS_INGEST_LAST_TS)) or 0
    gap_start_raw = await redis_client.get(REDIS_BACKFILL_GAP_START)

    silent = now - last_push
    if silent > BACKFILL_GAP_THRESHOLD_S:
        # 推送中断中：冻结缺口起点（仅一次，与 EMS 连接状态无关）
        if gap_start_raw is None and last_ts:
            await redis_client.set(REDIS_BACKFILL_GAP_START, last_ts)
            logger.warning(
                "检测到推送中断，记录缺口起点",
                extra={"extra_fields": {"gap_start": last_ts, "silent_s": silent}},
            )
        return

    # 推送正常
    if gap_start_raw is None:
        return  # 无未处理缺口

    manager = get_manager()
    if manager is None or not manager.client.token:
        return  # EMS 未恢复连接，留待下轮

    gap_start = _to_int(gap_start_raw) or 0
    gap_end = last_ts or now
    if gap_end <= gap_start:
        await redis_client.delete(REDIS_BACKFILL_GAP_START)
        return

    # 审查 B2：限制单次回补窗口跨度，防止 last_ts 长期不前进导致窗口无界、分片爆炸。
    # 截断时保留 gap_start，本轮只补最近窗口，剩余留待下轮续补。
    if gap_end - gap_start > BACKFILL_MAX_WINDOW_S:
        capped_end = gap_start + BACKFILL_MAX_WINDOW_S
        logger.warning(
            "缺口窗口超上限，本轮仅回补部分窗口，剩余待下轮",
            extra={"extra_fields": {
                "gap_start": gap_start, "gap_end": gap_end, "capped_end": capped_end,
            }},
        )
        gap_end = capped_end

    points = await _active_point_ids()
    if not points:
        # 审查 B3：无活跃测点时此前 run_backfill 返回 skipped(empty) 被当作「补失败」静默保留缺口，
        # 每轮空转 warning 且无指标。改为显式记失败指标并提前返回，使其可观测。
        await record_failure(M_BACKFILL_WATCH, error="no_active_points")
        logger.warning(
            "推送已恢复但无活跃测点，无法回补，保留缺口待测点恢复",
            extra={"extra_fields": {"gap_start": gap_start, "gap_end": gap_end}},
        )
        return

    logger.info(
        "检测到推送恢复，触发断连回补",
        extra={"extra_fields": {"gap_start": gap_start, "gap_end": gap_end}},
    )
    try:
        result = await run_backfill(manager.client, points, gap_start, gap_end)
    except Exception:
        # run_backfill 内已记 sync_log 与日志；保留缺口待下轮重补，不在此吞成功
        logger.error("断连回补执行异常，保留缺口待下轮重补")
        return
    # 审查 I1：仅当本轮无可重试失败、且未因历史锁被跳过时才清缺口；
    # 否则保留缺口待下轮重补，避免一次网络抖动导致整段缺口永久丢失。
    if not result.skipped and result.failed_slices == 0:
        await redis_client.delete(REDIS_BACKFILL_GAP_START)
    else:
        logger.warning(
            "回补存在失败分片或被锁跳过，保留缺口待重补",
            extra={"extra_fields": {
                "skipped": result.skipped, "failed_slices": result.failed_slices,
            }},
        )
