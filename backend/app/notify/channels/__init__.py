"""渠道适配器注册表。"""
from __future__ import annotations

from app.notify.channels.base import ChannelAdapter, ChannelError, ChannelSkip, NotifyMessage
from app.notify.channels.dingtalk import DingtalkAdapter
from app.notify.channels.email import EmailAdapter
from app.notify.channels.sms import SmsAdapter
from app.notify.channels.voice import VoiceAdapter
from app.notify.channels.webhook import WebhookAdapter
from app.notify.channels.wecom import WecomAdapter

_ADAPTERS: dict[str, ChannelAdapter] = {
    "sms": SmsAdapter(),
    "email": EmailAdapter(),
    "dingtalk": DingtalkAdapter(),
    "wecom": WecomAdapter(),
    "voice": VoiceAdapter(),
    "webhook": WebhookAdapter(),
}

SUPPORTED_TYPES = frozenset(_ADAPTERS)


def get_adapter(channel_type: str) -> ChannelAdapter | None:
    return _ADAPTERS.get(channel_type)


__all__ = [
    "ChannelAdapter",
    "ChannelError",
    "ChannelSkip",
    "NotifyMessage",
    "get_adapter",
    "SUPPORTED_TYPES",
]
