"""邮件渠道：通过 SMTP 发送（stdlib smtplib，置于线程执行避免阻塞事件循环）。

config：smtp_host（必填）、smtp_port、username、smtp_password（敏感）、from_addr、use_tls。
"""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.text import MIMEText
from typing import Any

from app.core.constants import NOTIFY_HTTP_TIMEOUT_S
from app.notify.channels.base import ChannelError, ChannelSkip, NotifyMessage


def _send_sync(config: dict[str, Any], to_addr: str, subject: str, body: str) -> None:
    host = config.get("smtp_host")
    if not host:
        raise ChannelError("缺少 smtp_host")
    port = int(config.get("smtp_port", 25))
    from_addr = config.get("from_addr") or config.get("username") or "dcim@local"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=NOTIFY_HTTP_TIMEOUT_S) as server:
            if config.get("use_tls"):
                server.starttls()
            if config.get("username"):
                server.login(config["username"], config.get("smtp_password", ""))
            server.sendmail(from_addr, [to_addr], msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise ChannelError(f"SMTP 发送失败: {exc}") from exc


class EmailAdapter:
    type = "email"

    async def send(
        self, config: dict[str, Any], recipient: dict[str, Any], message: NotifyMessage
    ) -> str:
        to_addr = recipient.get("email")
        if not to_addr:
            raise ChannelSkip("接收人无邮箱")
        await asyncio.to_thread(_send_sync, config, to_addr, message.subject, message.content)
        return to_addr

    async def test(self, config: dict[str, Any]) -> None:
        host = config.get("smtp_host")
        if not host:
            raise ChannelError("缺少 smtp_host")

        def _probe() -> None:
            try:
                with smtplib.SMTP(host, int(config.get("smtp_port", 25)),
                                  timeout=NOTIFY_HTTP_TIMEOUT_S) as server:
                    server.noop()
            except (smtplib.SMTPException, OSError) as exc:
                raise ChannelError(f"SMTP 连通失败: {exc}") from exc

        await asyncio.to_thread(_probe)
