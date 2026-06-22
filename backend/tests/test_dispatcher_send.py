"""通知派发健壮性测试（审查 M5/I6）。

- _send_one 对未预期异常隔离：记 failed 日志 + 指标，不向上冒泡（保证同批其余渠道继续）。
- decrypt_config 解密失败回退原值且记错（不静默）。
用桩 db/channel/recipient/adapter，避免依赖含 PG 类型的 notify 模型与真实 DB。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from app.core import metrics
from app.models.notify import NotifyChannel, NotifyLog, Recipient
from app.notify import dispatcher
from app.notify.channels.base import NotifyMessage
from app.notify.config_crypto import decrypt_config
from sqlalchemy.ext.asyncio import AsyncSession

_MSG = NotifyMessage(
    subject="s", content="c", level=2, trigger="raise", resource_id="p1", alarm_id=7
)


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


async def test_send_one_isolates_unexpected_exception(fake_redis, monkeypatch):
    """适配器抛非 ChannelError 异常 → 记 failed、记指标、不抛出。"""
    class _BoomAdapter:
        type = "webhook"

        async def send(self, config, recipient, message):
            raise RuntimeError("adapter internal bug")

    monkeypatch.setattr(dispatcher, "get_adapter", lambda _t: _BoomAdapter())
    db = _FakeDB()
    channel = SimpleNamespace(type="webhook", config={}, id=1)
    recipient = SimpleNamespace(
        name="oncall", phone=None, email=None, dingtalk_id=None, wecom_id=None
    )

    # 不应抛出（duck-typed 桩 cast 为签名类型，仅访问被用到的属性）
    await dispatcher._send_one(
        cast(AsyncSession, db), cast(NotifyChannel, channel), cast(Recipient, recipient), _MSG
    )

    assert len(db.added) == 1
    log = cast(NotifyLog, db.added[0])
    assert log.status == "failed"
    failures = await metrics.get_failures()
    assert failures.get(metrics.M_NOTIFY_SEND, {}).get("count") == 1


async def test_broadcast_channel_delivers_once_without_recipients(fake_redis, monkeypatch):
    """审查 H1：群机器人渠道（webhook/钉钉/企微）即使路由无接收组，也必须发送一次——
    此前 channels×recipients 嵌套循环在 recipients 为空时一条都不发、不记日志/指标。"""
    sent_calls: list[dict] = []

    class _BroadcastAdapter:
        type = "webhook"
        broadcast = True

        async def send(self, config, recipient, message):
            sent_calls.append({"recipient": recipient})
            return "http://hook"

    monkeypatch.setattr(dispatcher, "get_adapter", lambda _t: _BroadcastAdapter())
    db = _FakeDB()
    channel = SimpleNamespace(type="webhook", config={}, id=1, name="运维群机器人")
    targets = dispatcher._Targets(
        route=cast("dispatcher.NotifyRoute", SimpleNamespace(notify_on_recover=True)),
        channels=[cast(NotifyChannel, channel)],
        recipients=[],  # 接收组为空
    )

    sent = await dispatcher._deliver(cast(AsyncSession, db), targets, _MSG)

    assert sent == 1  # 群机器人发送一次
    assert len(sent_calls) == 1
    log = cast(NotifyLog, db.added[0])
    assert log.status == "sent"


async def test_p2p_channel_skips_when_no_recipients(fake_redis, monkeypatch):
    """点对点渠道（短信等）无接收人时不发送（无地址可投递），但不静默——记 warning。"""
    sent_calls: list[dict] = []

    class _P2PAdapter:
        type = "sms"
        broadcast = False

        async def send(self, config, recipient, message):
            sent_calls.append({"recipient": recipient})
            return "138..."

    monkeypatch.setattr(dispatcher, "get_adapter", lambda _t: _P2PAdapter())
    db = _FakeDB()
    channel = SimpleNamespace(type="sms", config={}, id=2, name="短信")
    targets = dispatcher._Targets(
        route=cast("dispatcher.NotifyRoute", SimpleNamespace(notify_on_recover=True)),
        channels=[cast(NotifyChannel, channel)],
        recipients=[],
    )

    sent = await dispatcher._deliver(cast(AsyncSession, db), targets, _MSG)
    assert sent == 0
    assert sent_calls == []


async def test_decrypt_config_falls_back_and_logs(fake_redis, caplog):
    """无法解密的敏感字段回退原值，记 ERROR 且上报 M_NOTIFY_DECRYPT 指标（不静默）。"""
    import logging

    with caplog.at_level(logging.ERROR):
        out = await decrypt_config({"secret": "not-a-valid-fernet-token", "url": "http://x"})
    assert out["secret"] == "not-a-valid-fernet-token"  # 回退原值
    assert out["url"] == "http://x"  # 非敏感字段原样
    assert any("解密失败" in r.message for r in caplog.records)
    # 审查 B6：解密失败必须上报指标（此前定义却零引用）
    failures = await metrics.get_failures()
    assert failures.get(metrics.M_NOTIFY_DECRYPT, {}).get("count") == 1
