"""通知分发器：按级别路由 → 渠道集合 + 接收组 → 解析接收人 → 发送 → 重试 → notify_logs。

防轰炸（开发约定「防轰炸/去抖/恢复」，联动抑制模块；注：红线 #7 指混合告警源，非防轰炸）：
- 首发：新告警立即发送。
- 合并期内的重复（merge）只累计，不逐条发送。
- 周期摘要：flush_digests 定时把累计的合并次数汇总成一条摘要发送。
- masked（屏蔽/维护窗口）告警不发送。
- 恢复通知按 notify_route.notify_on_recover 开关。

事件来源：订阅 CHANNEL_ALARM_EVENTS（lifecycle 提交后发布）。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    CHANNEL_ALARM_EVENTS,
    NOTIFY_MAX_RETRY,
    NOTIFY_RETRY_BACKOFF_S,
    NOTIFY_TRIGGER_DIGEST,
    NOTIFY_TRIGGER_RAISE,
    NOTIFY_TRIGGER_RECOVER,
    REDIS_NOTIFY_DIGEST,
    REDIS_NOTIFY_DIGEST_META,
)
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.metrics import M_NOTIFY_SEND, record_failure
from app.core.redis import redis_client
from app.models.alarm import Alarm
from app.models.notify import (
    NotifyChannel,
    NotifyLog,
    NotifyRoute,
    Recipient,
    RecipientGroupMember,
)
from app.notify.channels import ChannelError, ChannelSkip, NotifyMessage, get_adapter
from app.notify.config_crypto import decrypt_config

logger = get_logger("notify")

LEVEL_NAME = {1: "紧急", 2: "严重", 3: "重要", 4: "次要", 5: "提示"}


# ---- 纯函数（可离线单测）----
def route_for_level(routes: Sequence[Any], level: int) -> Any | None:
    """选取匹配级别且启用的路由（取第一条）。routes 元素需有 level/enabled 属性。"""
    for r in routes:
        if r.enabled and r.level == level:
            return r
    return None


def render_subject(level: int, trigger: str, resource_id: str) -> str:
    tag = {"raise": "告警", "recover": "恢复", "digest": "告警摘要"}.get(trigger, "通知")
    return f"[{LEVEL_NAME.get(level, '?')}{tag}] {resource_id}"


def digest_text(resource_id: str, level: int, count: int, content: str | None) -> str:
    return (
        f"[{LEVEL_NAME.get(level, '?')}告警摘要] {resource_id} 在合并窗口内共发生 {count} 次。"
        f"最近内容：{content or ''}"
    )


@dataclass
class _Targets:
    route: NotifyRoute
    channels: list[NotifyChannel]
    recipients: list[Recipient]


async def _load_targets(db: AsyncSession, level: int) -> _Targets | None:
    routes = (
        await db.execute(select(NotifyRoute).where(NotifyRoute.level == level))
    ).scalars().all()
    route = route_for_level(routes, level)
    if route is None:
        return None
    channels = (
        await db.execute(
            select(NotifyChannel).where(
                NotifyChannel.id.in_(route.channel_ids or []), NotifyChannel.enabled.is_(True)
            )
        )
    ).scalars().all()
    recipients: list[Recipient] = []
    if route.group_ids:
        recipient_rows = (
            await db.execute(
                select(Recipient)
                .join(RecipientGroupMember, RecipientGroupMember.recipient_id == Recipient.id)
                .where(
                    RecipientGroupMember.group_id.in_(route.group_ids),
                    Recipient.enabled.is_(True),
                )
                .distinct()
            )
        ).scalars().all()
        recipients = list(recipient_rows)
    return _Targets(route=route, channels=list(channels), recipients=recipients)


async def _send_one(
    db: AsyncSession,
    channel: NotifyChannel,
    recipient: Recipient,
    message: NotifyMessage,
) -> None:
    """单渠道单接收人发送，含重试，写 notify_logs。"""
    adapter = get_adapter(channel.type)
    if adapter is None:
        # 审查 B5：未注册渠道类型此前静默 return，告警一条不发且无 log/指标/notify_log，
        # 运维面板误判正常。改为写 failed 日志 + 指标，使配置错误可观测。
        db.add(NotifyLog(
            alarm_id=message.alarm_id, channel_id=channel.id, recipient=recipient.name,
            trigger=message.trigger, status="failed",
            error=f"未知渠道类型: {channel.type}", retry_count=0,
        ))
        await record_failure(M_NOTIFY_SEND, error=f"unknown_channel_type:{channel.type}")
        logger.error(
            "通知渠道类型未注册，告警未发送",
            extra={"extra_fields": {"channel_id": channel.id, "type": channel.type}},
        )
        return
    cfg = await decrypt_config(channel.config)
    recipient_dict = {
        "name": recipient.name, "phone": recipient.phone, "email": recipient.email,
        "dingtalk_id": recipient.dingtalk_id, "wecom_id": recipient.wecom_id,
    }
    attempts = 1 + NOTIFY_MAX_RETRY
    last_err = ""
    for i in range(attempts):
        try:
            addr = await adapter.send(cfg, recipient_dict, message)
        except ChannelSkip:
            return  # 无该渠道地址，跳过不记录
        except ChannelError as exc:
            last_err = str(exc)
            if i < attempts - 1:
                await asyncio.sleep(NOTIFY_RETRY_BACKOFF_S)
                continue
        except Exception as exc:
            # 审查 M5：未预期异常（适配器内部 bug/未包装错误）不得冒泡中断同批其余渠道，
            # 记为不可重试失败并继续。
            last_err = f"未预期异常: {exc}"
            logger.error(
                "通知渠道发送未预期异常",
                extra={"extra_fields": {"channel_id": channel.id, "error": str(exc)}},
            )
            break
        else:
            db.add(NotifyLog(
                alarm_id=message.alarm_id, channel_id=channel.id, recipient=addr,
                trigger=message.trigger, status="sent", retry_count=i,
            ))
            return
    db.add(NotifyLog(
        alarm_id=message.alarm_id, channel_id=channel.id, recipient=recipient.name,
        trigger=message.trigger, status="failed", error=last_err[:500],
        retry_count=NOTIFY_MAX_RETRY,
    ))
    await record_failure(M_NOTIFY_SEND, error=last_err)


async def _deliver(db: AsyncSession, targets: _Targets, message: NotifyMessage) -> int:
    sent = 0
    for channel in targets.channels:
        for recipient in targets.recipients:
            await _send_one(db, channel, recipient, message)
            sent += 1
    return sent


async def dispatch_alarm(alarm_id: int, trigger: str) -> None:
    """分发单条告警的首发/恢复通知。"""
    async with AsyncSessionLocal() as db:
        alarm = await db.get(Alarm, alarm_id)
        if alarm is None or alarm.masked:
            return  # masked 不发
        targets = await _load_targets(db, alarm.level)
        if targets is None:
            return
        if trigger == NOTIFY_TRIGGER_RECOVER and not targets.route.notify_on_recover:
            return
        message = NotifyMessage(
            subject=render_subject(alarm.level, trigger, alarm.resource_id),
            content=(alarm.content or "") if trigger != NOTIFY_TRIGGER_RECOVER
            else f"{alarm.content or ''}（已恢复）",
            level=alarm.level, trigger=trigger, resource_id=alarm.resource_id,
            alarm_id=alarm.id, merge_count=alarm.merge_count,
        )
        await _deliver(db, targets, message)
        await db.commit()


async def _accumulate_digest(ev: dict[str, Any]) -> None:
    """合并期内重复事件：累计计数与最近元信息，待 flush_digests 汇总。"""
    merge_key = ev.get("merge_key")
    if not merge_key:
        return
    await redis_client.hincrby(REDIS_NOTIFY_DIGEST, merge_key, 1)
    await redis_client.hset(
        REDIS_NOTIFY_DIGEST_META,
        merge_key,
        json.dumps({"level": ev.get("level"), "resource_id": ev.get("resource_id"),
                    "content": ev.get("content"), "alarm_id": ev.get("alarm_id")}),
    )


async def flush_digests() -> int:
    """周期摘要：把累计的合并次数汇总成摘要发送，并清空累计。返回发送的摘要数。

    审查 I4：此前「hgetall 取快照 → 逐 key hdel」之间，dispatcher worker 的 hincrby 增量会被
    随后的 hdel 整条删除而丢失。改为用 RENAME 原子「抽走」当前累计哈希——之后的 hincrby 落入
    新建的同名哈希，留待下轮 flush，不再丢计数。
    """
    tmp_counts = f"{REDIS_NOTIFY_DIGEST}:flushing"
    tmp_meta = f"{REDIS_NOTIFY_DIGEST_META}:flushing"
    try:
        # RENAME 源不存在会抛错；无累计时直接返回
        await redis_client.rename(REDIS_NOTIFY_DIGEST, tmp_counts)
    except Exception:
        return 0
    try:
        await redis_client.rename(REDIS_NOTIFY_DIGEST_META, tmp_meta)
    except Exception:
        pass  # meta 可能不存在，容忍

    counts = await redis_client.hgetall(tmp_counts)
    metas = await redis_client.hgetall(tmp_meta)
    flushed = 0
    async with AsyncSessionLocal() as db:
        for merge_key, count_s in counts.items():
            meta = json.loads(metas.get(merge_key) or "{}")
            level = int(meta.get("level") or 5)
            resource_id = str(meta.get("resource_id") or merge_key)
            targets = await _load_targets(db, level)
            if targets is not None:
                message = NotifyMessage(
                    subject=render_subject(level, NOTIFY_TRIGGER_DIGEST, resource_id),
                    content=digest_text(resource_id, level, int(count_s), meta.get("content")),
                    level=level, trigger=NOTIFY_TRIGGER_DIGEST, resource_id=resource_id,
                    alarm_id=meta.get("alarm_id"), merge_count=int(count_s),
                )
                await _deliver(db, targets, message)
                flushed += 1
        await db.commit()
    await redis_client.delete(tmp_counts, tmp_meta)
    if flushed:
        logger.info("已发送周期告警摘要", extra={"extra_fields": {"count": flushed}})
    return flushed


async def _handle_event(ev: dict[str, Any]) -> None:
    kind = ev.get("kind")
    if kind == NOTIFY_TRIGGER_RAISE:
        await dispatch_alarm(int(ev["alarm_id"]), NOTIFY_TRIGGER_RAISE)
    elif kind == NOTIFY_TRIGGER_RECOVER:
        await dispatch_alarm(int(ev["alarm_id"]), NOTIFY_TRIGGER_RECOVER)
    elif kind == "merge":
        await _accumulate_digest(ev)


# ---- 事件订阅 worker（受监督：异常自动重订阅，避免静默退出）----
_worker_task: asyncio.Task[None] | None = None
_worker_stop: asyncio.Event | None = None


async def _worker() -> None:
    assert _worker_stop is not None
    while not _worker_stop.is_set():
        pubsub = redis_client.pubsub()
        try:
            await pubsub.subscribe(CHANNEL_ALARM_EVENTS)
            logger.info("通知 worker 已订阅告警事件总线")
            # 用 get_message(timeout) 轮询：空闲超时返回 None 而非抛错，订阅保持存活。
            while not _worker_stop.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None or msg.get("type") != "message":
                    continue
                try:
                    ev = json.loads(msg["data"])
                except (json.JSONDecodeError, TypeError, KeyError):
                    continue
                try:
                    await _handle_event(ev)
                except Exception as exc:
                    logger.error("通知分发失败", extra={"extra_fields": {"error": str(exc)}})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "通知 worker 订阅中断，2s 后重订阅",
                extra={"extra_fields": {"error": repr(exc)}},
            )
            await asyncio.sleep(2)
        finally:
            try:
                await pubsub.aclose()
            except Exception:
                pass


async def start_notify_worker() -> None:
    global _worker_task, _worker_stop
    if _worker_task is None:
        _worker_stop = asyncio.Event()
        _worker_task = asyncio.create_task(_worker(), name="notify-worker")


async def stop_notify_worker() -> None:
    global _worker_task, _worker_stop
    if _worker_stop is not None:
        _worker_stop.set()
    if _worker_task is not None:
        _worker_task.cancel()
        _worker_task = None
    _worker_stop = None
