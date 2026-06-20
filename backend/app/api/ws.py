"""WebSocket 实时网关 /ws/realtime。

数据流（红线对应 04 数据流①）：采集层写最新值后发布 Redis Pub/Sub `channel:realtime`，
本网关订阅该频道，按客户端声明的测点集过滤后下推 {type:realtime, points:[...]}。

鉴权：内网从简但不裸奔（红线 #9）——连接需经 query 参数 token 校验 JWT，
失败即拒绝握手。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.constants import CHANNEL_REALTIME
from app.core.logging import get_logger
from app.core.redis import redis_client
from app.core.security import decode_access_token

logger = get_logger("ws")

router = APIRouter()


def _authenticate(token: str | None) -> str | None:
    """校验 JWT，返回用户名；失败返回 None。"""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


async def _client_reader(ws: WebSocket, state: dict[str, set[str]]) -> None:
    """读取客户端消息，维护订阅集合。"""
    while True:
        raw = await ws.receive_text()
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("action") == "subscribe":
            ids = msg.get("point_ids") or []
            state["subscribed"] = {str(i) for i in ids if i}
            logger.info(
                "WS 订阅更新",
                extra={"extra_fields": {"count": len(state["subscribed"])}},
            )


async def _pubsub_forwarder(ws: WebSocket, state: dict[str, set[str]]) -> None:
    """订阅 Redis 实时频道，按订阅集过滤后推送给客户端。"""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_REALTIME)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                frame = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
            subscribed = state.get("subscribed") or set()
            if not subscribed:
                continue  # 未声明订阅前不推送
            points: list[dict[str, Any]] = [
                p for p in (frame.get("points") or []) if p.get("id") in subscribed
            ]
            if points:
                await ws.send_text(
                    json.dumps({"type": "realtime", "points": points}, ensure_ascii=False)
                )
    finally:
        await pubsub.unsubscribe(CHANNEL_REALTIME)
        await pubsub.aclose()


@router.websocket("/ws/realtime")
async def ws_realtime(websocket: WebSocket, token: str | None = None) -> None:
    username = _authenticate(token)
    if username is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    state: dict[str, set[str]] = {"subscribed": set()}
    reader = asyncio.create_task(_client_reader(websocket, state))
    forwarder = asyncio.create_task(_pubsub_forwarder(websocket, state))
    try:
        done, pending = await asyncio.wait(
            {reader, forwarder}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        # 取出已完成任务异常（WebSocketDisconnect 视为正常断连）
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                logger.warning("WS 任务异常", extra={"extra_fields": {"error": str(exc)}})
    except WebSocketDisconnect:
        pass
    finally:
        for task in (reader, forwarder):
            if not task.done():
                task.cancel()
        logger.info("WS 连接关闭", extra={"extra_fields": {"user": username}})
