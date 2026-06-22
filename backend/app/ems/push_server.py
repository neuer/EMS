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


async def _parse_data(request: Request) -> dict[str, Any]:
    """解析推送包体的 data 段。

    审查 S1：解析失败（非法 JSON / body 非 dict）必须抛出，由端点记 parse_failed 指标——
    区别于「合法空包」（dict 但缺 data 键，返回 {}）。此前裸 except 一律回退 {} 会让 EMS
    报文格式漂移（版本/编码/包头变化）导致每一条推送被静默丢弃而面板显示正常，是监控平台
    最危险的故障模式（自身失明）。
    """
    body = await request.json()  # 非法 JSON 抛异常，由端点捕获
    if not isinstance(body, dict):
        raise ValueError("推送包体非 JSON 对象")
    return body.get("data", {})


@router.post("/online_data_push")
async def online_data_push(request: Request) -> dict[str, Any]:
    """实时数据推送接收。无论处理结果如何都需 ack，避免 EMS 重试风暴；
    解析失败与处理失败均记指标（不静默吞错）。"""
    try:
        data = await _parse_data(request)
    except Exception as exc:
        # 审查 S1：包体解析失败始终 ack（避免重试风暴），但必须记指标使「报文漂移」可观测。
        logger.error("实时推送包体解析失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_INGEST_PUSH_HANDLE, error=f"parse_failed: {exc}")
        return _ACK
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
    try:
        data = await _parse_data(request)
    except Exception as exc:
        logger.error("告警推送包体解析失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_INGEST_PUSH_HANDLE, error=f"parse_failed: {exc}")
        return _ACK
    try:
        count = await handle_alarm_push(data)
        logger.info("收到告警推送", extra={"extra_fields": {"processed": count}})
    except Exception as exc:
        logger.error("处理告警推送失败", extra={"extra_fields": {"error": str(exc)}})
        await record_failure(M_INGEST_PUSH_HANDLE, error=str(exc))
    return _ACK
