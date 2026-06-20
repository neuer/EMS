"""健康检查：DB / Redis / EMS 连接状态。

EMS 状态取自连接管理写入 Redis 的 ems:conn 哈希（state 字段）；
未配置/未连接过 EMS 时回退 not_configured。健康判定不依赖 EMS（只读对接、
允许 EMS 暂时离线而平台仍提供历史/查询能力）。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.constants import REDIS_EMS_CONN
from app.core.db import check_db
from app.core.metrics import get_failures
from app.core.redis import check_redis, redis_client

router = APIRouter(tags=["健康检查"])


async def _ems_state() -> str:
    """读取 EMS 连接状态（不阻断健康判定）；异常或缺失回退 not_configured。"""
    try:
        raw = await redis_client.hgetall(REDIS_EMS_CONN)
    except Exception:
        return "not_configured"
    state = raw.get("state") if isinstance(raw, dict) else None
    return str(state) if state else "not_configured"


@router.get("/health")
async def health() -> dict[str, object]:
    db_ok = await check_db()
    redis_ok = await check_redis()
    overall = db_ok and redis_ok
    return {
        "status": "ok" if overall else "degraded",
        "components": {
            "db": "up" if db_ok else "down",
            "redis": "up" if redis_ok else "down",
            # EMS 真实连接状态（online/connecting/offline/not_configured）
            "ems": await _ems_state(),
        },
        # 失败可观测（红线 #10.1）：各关键链路累计失败次数与最近失败时刻，
        # 供运维/告警发现「日志吞掉的静默失败」。空字典表示无失败记录。
        "failures": await get_failures(),
    }
