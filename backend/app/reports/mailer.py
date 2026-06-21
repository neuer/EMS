"""报表邮件发送（SMTP，支持附件）。

复用通知邮件渠道（notify_channels.type='email'）的 SMTP 配置；敏感字段 smtp_password
以 Fernet 加密存储，发送时用 core.crypto 解密（不耦合 notify 业务逻辑）。
SMTP 阻塞调用置于线程，避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.core.constants import CHANNEL_SENSITIVE_KEYS, NOTIFY_HTTP_TIMEOUT_S
from app.core.crypto import decrypt
from app.core.logging import get_logger
from app.core.metrics import M_NOTIFY_DECRYPT, record_failure

logger = get_logger("notify")


class MailerError(RuntimeError):
    """邮件发送失败。"""


def _resolve_password(config: dict[str, Any]) -> tuple[str, bool]:
    """返回 (明文密码, 是否解密失败)。解密失败回退原值，由调用方上报指标。"""
    raw = config.get("smtp_password", "")
    if isinstance(raw, str) and raw and "smtp_password" in CHANNEL_SENSITIVE_KEYS:
        try:
            return decrypt(raw), False
        except ValueError:
            # 审查 I6/B6：解密失败显式记错（不含密文），回退原值将导致 SMTP 登录显式失败
            logger.error("邮件渠道 smtp_password 解密失败，SMTP 登录可能失败")
            return raw, True
    return raw or "", False


def _send_sync(
    config: dict[str, Any],
    password: str,
    to_addrs: list[str],
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
) -> None:
    host = config.get("smtp_host")
    if not host:
        raise MailerError("邮件渠道缺少 smtp_host")
    port = int(config.get("smtp_port", 25))
    from_addr = config.get("from_addr") or config.get("username") or "dcim@local"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for filename, content in attachments:
        part = MIMEApplication(content)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    try:
        with smtplib.SMTP(host, port, timeout=NOTIFY_HTTP_TIMEOUT_S) as server:
            if config.get("use_tls"):
                server.starttls()
            if config.get("username"):
                server.login(config["username"], password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise MailerError(f"SMTP 发送失败: {exc}") from exc


async def send_report_mail(
    config: dict[str, Any],
    to_addrs: list[str],
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
) -> None:
    """异步发送报表邮件（含附件）。config 为邮件渠道原始 config（内部解密密码）。"""
    if not to_addrs:
        raise MailerError("无有效收件人邮箱")
    # 审查 B6：在异步上下文预解析密码并上报解密失败指标（_send_sync 在线程内无法 await）。
    password, decrypt_failed = _resolve_password(config)
    if decrypt_failed:
        await record_failure(M_NOTIFY_DECRYPT, error="field=smtp_password")
    await asyncio.to_thread(_send_sync, config, password, to_addrs, subject, body, attachments)
