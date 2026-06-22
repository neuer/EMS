"""实时数据推送处理：解析 → Redis 最新值/设备状态 → Pub/Sub → 落 point_history。

共济报文（红线 #3）：分页包按 period 聚合；设备无测点时 points=null 需正常处理。
红线 #10：时间统一 Unix 秒 → TIMESTAMPTZ(UTC)。
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    CHANNEL_REALTIME,
    REALTIME_FALLBACK_GAP_S,
    REDIS_BACKFILL_GAP_START,
    REDIS_DEVICE_STATUS,
    REDIS_EMS_CONN,
    REDIS_INGEST_LAST_TS,
    REDIS_LATEST_TTL,
    REDIS_POINT_LATEST,
)
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.metrics import (
    M_INGEST_PARSE_DROP,
    M_INGEST_PERSIST,
    M_INGEST_REDIS,
    M_RULE_EVAL,
    record_failure,
)
from app.core.redis import redis_client
from app.engine import rules as rule_engine
from app.models.asset import DeviceStatus

logger = get_logger("ingest")


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


def _to_utc(save_time: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(save_time), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


async def handle_data_push(data: dict[str, Any]) -> int:
    """处理一轮实时数据推送。返回落库测点数。"""
    devices = data.get("devices") or []
    history_rows: list[dict[str, Any]] = []
    realtime_frame: list[dict[str, Any]] = []
    device_status_rows: list[dict[str, Any]] = []
    now_ts = datetime.now(UTC)
    dropped = 0  # 审查 F：脏数据（value/save_time 解析失败）丢弃计数，末尾上报一次

    pipe = redis_client.pipeline()
    for dev in devices:
        device_id = dev.get("resource_id")
        if not device_id:
            continue
        status = dev.get("status", 1)
        try:
            status_int = int(status)
        except (TypeError, ValueError):
            status_int = 1
        pipe.set(REDIS_DEVICE_STATUS.format(device_id=device_id), status_int, ex=REDIS_LATEST_TTL)
        device_status_rows.append(
            {"device_id": device_id, "status": status_int, "updated_at": now_ts}
        )

        for p in dev.get("points") or []:  # points 可能为 null
            pid = p.get("resource_id")
            if not pid:
                continue
            raw_value = p.get("real_value")
            save_time = p.get("save_time")
            value = _to_float(raw_value)
            ts = _to_utc(save_time)
            # 审查 F：脏数据可观测——有原值却解析失败（非合法 None/数值）才计为丢弃
            if (raw_value is not None and value is None) or (
                save_time is not None and ts is None
            ):
                dropped += 1

            key = REDIS_POINT_LATEST.format(point_id=pid)
            # 审查 F：raw_value/save_time 为 None 时存空串，避免下游读到字面量 "None"
            pipe.hset(key, mapping={
                "value": "" if raw_value is None else str(raw_value),
                "save_time": "" if save_time is None else str(save_time),
            })
            pipe.expire(key, REDIS_LATEST_TTL)

            if ts is not None:
                history_rows.append({"point_id": pid, "ts": ts, "value": value})
            realtime_frame.append({"id": pid, "value": value, "ts": save_time})

    # 写最新值 + last_push 状态（wall clock）+ 数据周期（供回补缺口判定）
    pipe.hset(REDIS_EMS_CONN, "last_push", int(time.time()))
    period = _to_int(data.get("period"))
    # 审查 S2：在 pipeline 推进 last_ts 之前读取「本批之前的最后有效时刻」，供落库失败时
    # 作为缺口起点——否则缺口起点会等于本批 period，使 gap_start==gap_end 被 backfill_watch 删除。
    prev_last_ts = _to_int(await redis_client.get(REDIS_INGEST_LAST_TS))
    if period is not None:
        pipe.set(REDIS_INGEST_LAST_TS, period)
    try:
        await pipe.execute()
    except Exception as exc:
        logger.error("写 Redis 最新值失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_INGEST_REDIS, error=str(exc))  # 审查 M2

    # 落库（原始层 + 设备状态）
    if history_rows or device_status_rows:
        try:
            async with AsyncSessionLocal() as db:
                await _persist(db, history_rows, device_status_rows)
                await db.commit()
        except Exception as exc:
            # 审查 S2：落库失败此前被吞且已 ack EMS（不重推）→ 原始数据永久丢失且上层误判成功。
            # 改为：记指标 + 冻结回补缺口起点（NX，不覆盖更早缺口），使本批落入 offline_value
            # 回补窗口由 backfill_watch 补回，真正做到「数据不丢」。
            logger.error("实时数据落库失败", extra={"extra_fields": {"error": str(exc)}})
            await record_failure(M_INGEST_PERSIST, error=str(exc))
            if period is not None:
                # 审查 S2：缺口起点取「本批之前的最后有效时刻」；无更早时刻时回退 period-步长。
                # 关键是 gap_start < period(=last_ts)，使回补窗口 [gap_start, period] 非空。
                gap_start = (
                    prev_last_ts
                    if prev_last_ts is not None and prev_last_ts < period
                    else period - REALTIME_FALLBACK_GAP_S
                )
                try:
                    await redis_client.set(REDIS_BACKFILL_GAP_START, gap_start, nx=True)
                except Exception as gap_exc:
                    # 审查 C1：缺口标记是「数据不丢」的最后一环；此前裸 pass 吞错会让本批
                    # 既未落库又未记缺口 → 永久静默丢失且无人可知。改为显式记日志 + 指标。
                    logger.error(
                        "落库失败后缺口标记写入也失败，该批数据可能永久丢失",
                        extra={"extra_fields": {"period": period, "error": str(gap_exc)}},
                    )
                    await record_failure(M_INGEST_PERSIST, error=f"gap_mark_failed: {gap_exc}")

    # 发布 Pub/Sub（WebSocket 网关 Sprint 2 订阅）
    if realtime_frame:
        try:
            await redis_client.publish(
                CHANNEL_REALTIME,
                json.dumps({"type": "realtime", "points": realtime_frame}, ensure_ascii=False),
            )
        except Exception as exc:
            logger.error("发布实时帧失败", extra={"extra_fields": {"error": str(exc)}})

    # 喂规则引擎（Sprint 3）：仅数值型测点参与阈值评估。
    # 审查 C3：ts 用 _to_int 容错——此前 int(f["ts"]) 遇脏 save_time（非数字串）会抛 ValueError
    # 拖垮整批 evaluate_batch（本批所有测点漏判越限）。逐点剔除坏时间戳而非整批崩溃。
    eval_items = [
        (f["id"], f["value"], ts)
        for f in realtime_frame
        if f["value"] is not None and (ts := _to_int(f["ts"])) is not None
    ]
    if eval_items:
        try:
            await rule_engine.evaluate_batch(eval_items)
        except Exception as exc:
            # 审查 M1：规则评估失败=这批测点越限未被检测（漏判），记指标使其可观测。
            logger.error("规则评估失败", extra={"extra_fields": {"error": str(exc)}})
            await record_failure(M_RULE_EVAL, error=str(exc))

    # 审查 F：本批脏数据丢弃数 >0 时上报一次（避免逐点日志噪声），使数据质量恶化可观测
    if dropped:
        await record_failure(M_INGEST_PARSE_DROP, error=f"count={dropped}")

    return len(history_rows)


# point_history 为 TimescaleDB hypertable，无 ORM 模型，用参数化 SQL 落库（幂等）
_INSERT_HISTORY = text(
    "INSERT INTO point_history (point_id, ts, value) VALUES (:point_id, :ts, :value) "
    "ON CONFLICT (point_id, ts) DO UPDATE SET value = EXCLUDED.value"
)


async def _persist(
    db: AsyncSession,
    history_rows: list[dict[str, Any]],
    device_status_rows: list[dict[str, Any]],
) -> None:
    if history_rows:
        await db.execute(_INSERT_HISTORY, history_rows)

    for row in device_status_rows:
        stmt = pg_insert(DeviceStatus).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_id"],
            set_={"status": stmt.excluded["status"], "updated_at": stmt.excluded["updated_at"]},
        )
        await db.execute(stmt)
