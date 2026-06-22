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

from redis.exceptions import ResponseError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    CHANNEL_ALARM_EVENTS,
    CHANNEL_SECRET_MASK,
    CHANNEL_SENSITIVE_KEYS,
    NOTIFY_DEDUP_TTL_S,
    NOTIFY_DIGEST_HASH_TTL_S,
    NOTIFY_MAX_RETRY,
    NOTIFY_PENDING_MAX_ATTEMPTS,
    NOTIFY_RETRY_BACKOFF_S,
    NOTIFY_TRIGGER_DIGEST,
    NOTIFY_TRIGGER_RAISE,
    NOTIFY_TRIGGER_RECOVER,
    REDIS_NOTIFY_DEDUP,
    REDIS_NOTIFY_DIGEST,
    REDIS_NOTIFY_DIGEST_META,
    REDIS_NOTIFY_PENDING,
)
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.metrics import (
    M_ALARM_PUBLISH,
    M_NOTIFY_DIGEST,
    M_NOTIFY_SEND,
    record_failure,
)
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


def _collect_secrets(cfg: dict[str, Any]) -> list[str]:
    """从解密后的渠道 config 收集敏感明文值（顶层敏感键 + headers 值），用于错误文本脱敏。"""
    vals: list[str] = []
    for k, v in cfg.items():
        if k == "headers" and isinstance(v, dict):
            vals.extend(str(hv) for hv in v.values() if hv)
        elif k in CHANNEL_SENSITIVE_KEYS and v:
            vals.append(str(v))
    return vals


def _mask_secrets(text: str, cfg: dict[str, Any]) -> str:
    """审查 C4：网关错误响应可能回显请求体中的 secret，落 notify_logs 即明文入库（红线 #9）。
    用渠道凭据明文在错误文本上做替换为掩码，避免明文进入审计/日志。
    """
    for s in _collect_secrets(cfg):
        if s and s in text:
            text = text.replace(s, CHANNEL_SECRET_MASK)
    return text


async def _dedup_reserve(message: NotifyMessage, channel_id: int, recipient: str) -> bool:
    """审查 I1：发送前用 Redis SETNX 预留幂等键，避免 pending 重投 / worker 重复消费导致
    对同一 (alarm, channel, recipient, trigger) 重复外呼/发短信（§18/§19）。
    返回 True 表示成功预留（应发送）；False 表示近期已发送（跳过）。摘要类不去重（按窗口聚合）。
    """
    if message.trigger == NOTIFY_TRIGGER_DIGEST:
        return True
    key = REDIS_NOTIFY_DEDUP.format(
        alarm_id=message.alarm_id, channel_id=channel_id,
        recipient=recipient, trigger=message.trigger,
    )
    reserved = await redis_client.set(key, "1", nx=True, ex=NOTIFY_DEDUP_TTL_S)
    return bool(reserved)


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
    # 审查 I1：发送前幂等预留，重复投递（pending 重投/worker 重复消费）直接跳过外呼。
    if not await _dedup_reserve(message, channel.id, recipient.name):
        logger.debug(
            "通知幂等命中，跳过重复发送",
            extra={"extra_fields": {
                "alarm_id": message.alarm_id, "channel_id": channel.id,
                "recipient": recipient.name, "trigger": message.trigger,
            }},
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
    masked_err = _mask_secrets(last_err, cfg)
    db.add(NotifyLog(
        alarm_id=message.alarm_id, channel_id=channel.id, recipient=recipient.name,
        trigger=message.trigger, status="failed", error=masked_err[:500],
        retry_count=NOTIFY_MAX_RETRY,
    ))
    await record_failure(M_NOTIFY_SEND, error=masked_err)


def _broadcast_recipient(channel: NotifyChannel) -> Recipient:
    """群发型渠道的占位接收人：适配器忽略其地址字段，仅用渠道名作为 notify_log 标识。"""
    return Recipient(
        name=channel.name, phone=None, email=None, dingtalk_id=None, wecom_id=None, enabled=True
    )


async def _deliver(db: AsyncSession, targets: _Targets, message: NotifyMessage) -> int:
    """按渠道投递。

    审查 H1：群发型渠道（钉钉/企微/webhook 群机器人）不依赖接收人地址，即使路由无接收组
    也必须投递一次——此前 channels×recipients 嵌套循环在 recipients 为空时整条通知静默丢失。
    点对点渠道（短信/邮件/语音）仍按接收人迭代；无接收人时记 warning 使配置缺失可观测。
    """
    sent = 0
    for channel in targets.channels:
        adapter = get_adapter(channel.type)
        is_broadcast = adapter is not None and getattr(adapter, "broadcast", False)
        if is_broadcast:
            await _send_one(db, channel, _broadcast_recipient(channel), message)
            sent += 1
            continue
        if not targets.recipients:
            logger.warning(
                "点对点渠道无接收人，无法投递（请为该级别路由配置接收组）",
                extra={"extra_fields": {"channel_id": channel.id, "type": channel.type}},
            )
            continue
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
                    "content": ev.get("content"), "alarm_id": ev.get("alarm_id")},
                   ensure_ascii=False),
    )
    # 审查 I3：给累计 Hash 设兜底 TTL（> flush 周期）。若 flush 调度停摆，避免两个 Hash
    # 无限增长 + 告警明文长期滞留 Redis；正常情况下每轮 flush 会 RENAME 抽走、不受影响。
    await redis_client.expire(REDIS_NOTIFY_DIGEST, NOTIFY_DIGEST_HASH_TTL_S)
    await redis_client.expire(REDIS_NOTIFY_DIGEST_META, NOTIFY_DIGEST_HASH_TTL_S)


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
    except ResponseError:
        pass  # 审查 M8：no such key（无 meta 累计）属正常，容忍
    except Exception as exc:
        # 真实 Redis 故障：此前与「key 不存在」一并裸 except 吞掉，会让 metas 为空、摘要退化为
        # level=5/resource=merge_key 而可能整批不发。记 warning + 指标使其可观测。
        logger.warning(
            "摘要 meta 抽取失败（Redis 故障）", extra={"extra_fields": {"error": str(exc)}}
        )
        await record_failure(M_NOTIFY_DIGEST, error=str(exc))

    counts = await redis_client.hgetall(tmp_counts)
    metas = await redis_client.hgetall(tmp_meta)
    flushed = 0
    try:
        async with AsyncSessionLocal() as db:
            for merge_key, count_s in counts.items():
                try:
                    # 审查 F：单个 merge_key 的 meta 为脏值（手工改/版本切换）时跳过该 key，
                    # 不让一个坏值的 json.loads 抛错拖垮整轮其余摘要。
                    meta = json.loads(metas.get(merge_key) or "{}")
                except (ValueError, TypeError):
                    logger.warning("摘要 meta 解析失败，跳过该 key",
                                   extra={"extra_fields": {"merge_key": merge_key}})
                    continue
                # 审查 I2：单个 merge_key 的投递（_load_targets/_deliver）抛未预期异常时续跑，
                # 一个坏 key 不毁整轮其余摘要（此前会冒泡使本轮累计计数随 tmp 删除而全丢）。
                try:
                    level = int(meta.get("level") or 5)
                    resource_id = str(meta.get("resource_id") or merge_key)
                    targets = await _load_targets(db, level)
                    if targets is not None:
                        message = NotifyMessage(
                            subject=render_subject(level, NOTIFY_TRIGGER_DIGEST, resource_id),
                            content=digest_text(
                                resource_id, level, int(count_s), meta.get("content")
                            ),
                            level=level, trigger=NOTIFY_TRIGGER_DIGEST, resource_id=resource_id,
                            alarm_id=meta.get("alarm_id"), merge_count=int(count_s),
                        )
                        await _deliver(db, targets, message)
                        flushed += 1
                except Exception as exc:
                    logger.error("单条摘要投递失败，跳过", extra={"extra_fields": {
                        "merge_key": merge_key, "error": str(exc)}})
                    await record_failure(M_NOTIFY_DIGEST, error=str(exc))
            await db.commit()
    finally:
        # 审查 I2：tmp_* 清理放 finally，确保即便上面异常也不残留已抽走的累计哈希。
        await redis_client.delete(tmp_counts, tmp_meta)
    if flushed:
        logger.info("已发送周期告警摘要", extra={"extra_fields": {"count": flushed}})
    return flushed


async def retry_pending_events(max_n: int = 100) -> int:
    """重投发布失败的告警事件（审查 M2）。返回成功重投数。

    从补偿队列逐条取出，重新发布到事件总线；失败则尝试次数 +1 后回队，超过上限丢弃并记指标，
    避免坏事件无限重投。调度器周期调用。
    """
    sent = 0
    for _ in range(max_n):
        raw = await redis_client.lpop(REDIS_NOTIFY_PENDING)
        if raw is None:
            break
        if not isinstance(raw, str):  # decode_responses=True 下恒为 str；防御性收窄类型
            continue
        try:
            ev = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("补偿队列中存在脏事件，丢弃")
            continue
        attempts = int(ev.pop("_attempts", 0)) + 1
        try:
            await redis_client.publish(CHANNEL_ALARM_EVENTS, json.dumps(ev, ensure_ascii=False))
            sent += 1
        except Exception as exc:
            if attempts >= NOTIFY_PENDING_MAX_ATTEMPTS:
                logger.error(
                    "告警事件重投超过上限，丢弃（通知最终丢失）",
                    extra={"extra_fields": {"alarm_id": ev.get("alarm_id"), "attempts": attempts}},
                )
                await record_failure(M_ALARM_PUBLISH, error=f"retry_exhausted: {exc}")
            else:
                await redis_client.rpush(
                    REDIS_NOTIFY_PENDING,
                    json.dumps({**ev, "_attempts": attempts}, ensure_ascii=False),
                )
            break  # 发布通道异常，本轮不再继续，留待下轮
    if sent:
        logger.info("已重投发布失败的告警事件", extra={"extra_fields": {"count": sent}})
    return sent


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
