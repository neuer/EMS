"""EMS 推送接收端点（平台作为服务端）。

红线 #2：必须暴露 /north/online_data_push 与 /north/online_alarm_push，
返回 {"error_code":0,"error_msg":"ok","data":{"status":true}}。
挂在 login 上报的 recv_ip:recv_port（即 backend 对外地址），不带 token 校验
（EMS→平台推送方向不携带 token）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.logging import get_logger
from app.core.metrics import M_INGEST_PUSH_HANDLE, record_failure
from app.ingest.alarm import handle_alarm_push
from app.ingest.realtime import handle_data_push

logger = get_logger("ingest")

router = APIRouter(prefix="/north", tags=["EMS 推送接收"])

# 共济要求的固定 ack
_ACK = {"error_code": 0, "error_msg": "ok", "data": {"status": True}}


async def _read_data(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body.get("data", {}) if isinstance(body, dict) else {}


@router.post("/online_data_push")
async def online_data_push(request: Request) -> dict[str, Any]:
    """实时数据推送接收。无论处理结果如何都需 ack，避免 EMS 重试风暴；
    处理异常记录日志（不静默吞错）。"""
    data = await _read_data(request)
    try:
        count = await handle_data_push(data)
        logger.info("收到实时数据推送", extra={"extra_fields": {"points": count}})
    except Exception as exc:
        # 审查 S2：始终 ack 避免 EMS 重试风暴，但处理失败必须记指标（否则面板「推送正常」
        # 而底层整批未落库无人知）。
        logger.error("处理实时推送失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_INGEST_PUSH_HANDLE, error=str(exc))
    return _ACK


@router.post("/online_alarm_push")
async def online_alarm_push(request: Request) -> dict[str, Any]:
    """告警推送接收。红线 #7：仅纳 event_type∈{0,21,30}，阈值类丢弃去重。
    无论处理结果如何都 ack，避免 EMS 重试风暴。"""
    data = await _read_data(request)
    try:
        count = await handle_alarm_push(data)
        logger.info("收到告警推送", extra={"extra_fields": {"processed": count}})
    except Exception as exc:
        logger.error("处理告警推送失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_INGEST_PUSH_HANDLE, error=str(exc))
    return _ACK
