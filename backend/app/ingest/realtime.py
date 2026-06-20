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

            key = REDIS_POINT_LATEST.format(point_id=pid)
            pipe.hset(key, mapping={"value": str(raw_value), "save_time": str(save_time)})
            pipe.expire(key, REDIS_LATEST_TTL)

            if ts is not None:
                history_rows.append({"point_id": pid, "ts": ts, "value": value})
            realtime_frame.append({"id": pid, "value": value, "ts": save_time})

    # 写最新值 + last_push 状态（wall clock）+ 数据周期（供回补缺口判定）
    pipe.hset(REDIS_EMS_CONN, "last_push", int(time.time()))
    period = _to_int(data.get("period"))
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
                try:
                    await redis_client.set(REDIS_BACKFILL_GAP_START, period, nx=True)
                except Exception:
                    pass

    # 发布 Pub/Sub（WebSocket 网关 Sprint 2 订阅）
    if realtime_frame:
        try:
            await redis_client.publish(
                CHANNEL_REALTIME,
                json.dumps({"type": "realtime", "points": realtime_frame}, ensure_ascii=False),
            )
        except Exception as exc:
            logger.error("发布实时帧失败", extra={"extra_fields": {"error": str(exc)}})

    # 喂规则引擎（Sprint 3）：仅数值型测点参与阈值评估
    eval_items = [
        (f["id"], f["value"], int(f["ts"]))
        for f in realtime_frame
        if f["value"] is not None and f["ts"] is not None
    ]
    if eval_items:
        try:
            await rule_engine.evaluate_batch(eval_items)
        except Exception as exc:
            # 审查 M1：规则评估失败=这批测点越限未被检测（漏判），记指标使其可观测。
            logger.error("规则评估失败", extra={"extra_fields": {"error": str(exc)}})
            await record_failure(M_RULE_EVAL, error=str(exc))

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
