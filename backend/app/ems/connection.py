"""EMS 连接生命周期：登录 → 20s 心跳 → 退避重连 → 重订阅；状态写 redis ems:conn。

红线 #4：心跳 20s；遇 error_code 2/106 或心跳失败→重新登录并重订阅；指数退避。
红线 #1：纯只读；首连触发配置同步与数据订阅。
"""
from __future__ import annotations

import asyncio
import time

from app.core.config import settings
from app.core.constants import (
    CONN_STATE_CONNECTING,
    CONN_STATE_OFFLINE,
    CONN_STATE_ONLINE,
    EMS_SUSTAINED_OUTAGE_RECONNECTS,
    REDIS_EMS_CONN,
)
from app.core.crypto import decrypt
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.metrics import (
    M_EMS_HEARTBEAT,
    M_EMS_OFFLINE,
    M_EMS_RELOGIN,
    record_failure,
)
from app.core.redis import redis_client
from app.ems.client import EmsClient
from app.ems.protocol import EmsError
from app.models.system import EmsConfig
from app.sync.config_sync import SyncResult, run_config_sync

logger = get_logger("ems")


class ConnectionManager:
    """单实例连接管理。全局唯一，保证平台只持有一个 EMS 连接。"""

    def __init__(
        self,
        *,
        base_url: str,
        version: str,
        username: str,
        password: str,
        recv_ip: str,
        recv_port: str,
        subscribe_data: bool,
        subscribe_alarm: bool = True,
    ) -> None:
        self.client = EmsClient(base_url, version)
        self._username = username
        self._password = password
        self._recv_ip = recv_ip
        self._recv_port = recv_port
        self._subscribe_data = subscribe_data
        self._subscribe_alarm = subscribe_alarm

        self.heartbeat_interval = settings.ems_heartbeat_interval
        self.max_backoff = settings.ems_max_backoff

        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._reconnects = 0
        self._synced_once = False
        self._connected_ok = False
        self._consecutive_failures = 0  # 连续「连不上」次数，用于停摆升级判定

    # ---- 生命周期 ----
    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="ems-connection")
        logger.info("EMS 连接管理已启动")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        # 优雅退出：尝试 logout（PRD FR-1.6）
        try:
            if self.client.token:
                await self.client.logout()
        except Exception as exc:
            logger.warning("logout 失败", extra={"extra_fields": {"error": str(exc)}})
        await self.client.aclose()
        await self._set_state(CONN_STATE_OFFLINE, token_ok="0")
        logger.info("EMS 连接管理已停止")

    # ---- 主循环 ----
    async def _run(self) -> None:
        backoff = 1
        first = True
        while not self._stop.is_set():
            if not first:
                self._reconnects += 1
            first = False
            self._connected_ok = False
            try:
                await self._connect_cycle()
            except EmsError as exc:
                if exc.is_fatal:
                    logger.error(
                        "EMS 凭据错误，停止重连",
                        extra={"extra_fields": {"code": exc.code, "msg": exc.msg}},
                    )
                    await self._set_state(CONN_STATE_OFFLINE, token_ok="0")
                    break
                # 审查 M1：显式消费 need_relogin（2/106），让红线 #4「token/心跳失效→强制
                # 重登重订阅」的语义在代码中可见、可测，而非依赖「任何非致命错误都重连」的巧合。
                if exc.need_relogin:
                    logger.warning(
                        "EMS token/心跳失效，强制重登并重订阅 data+alarm",
                        extra={"extra_fields": {"code": exc.code, "msg": exc.msg}},
                    )
                    await record_failure(M_EMS_RELOGIN, error=f"code={exc.code}")
                else:
                    logger.warning(
                        "EMS 连接中断（业务错误），将重连",
                        extra={"extra_fields": {"code": exc.code, "msg": exc.msg}},
                    )
            except Exception as exc:
                logger.warning(
                    "EMS 连接中断，将重连", extra={"extra_fields": {"error": str(exc)}}
                )

            await self._set_state(CONN_STATE_OFFLINE, token_ok="0")
            if self._stop.is_set():
                break
            # 采集中断可观测（红线 #10.1）：记指标；连续「连不上」达阈值升级为 error。
            await record_failure(M_EMS_OFFLINE)
            if self._connected_ok:
                self._consecutive_failures = 0
                backoff = 1  # 上一次连接曾成功，退避重置
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= EMS_SUSTAINED_OUTAGE_RECONNECTS:
                    logger.error(
                        "EMS 连续重连失败，采集疑似停摆",
                        extra={"extra_fields": {
                            "consecutive_failures": self._consecutive_failures,
                            "reconnects": self._reconnects,
                        }},
                    )
            delay = min(backoff, self.max_backoff)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            if not self._connected_ok:
                backoff = min(backoff * 2, self.max_backoff)

    async def _connect_cycle(self) -> None:
        await self._set_state(CONN_STATE_CONNECTING)
        await self.client.login(
            self._username, self._password, self._recv_ip, self._recv_port
        )
        self._connected_ok = True
        await self._set_state(CONN_STATE_ONLINE, token_ok="1", last_heart=int(time.time()))
        logger.info("EMS 登录成功")

        # 首连执行配置同步（失败不阻断连接，留待定时任务重试）
        if not self._synced_once:
            try:
                await run_config_sync(self.client, batch_size=settings.ems_sync_batch_size)
                self._synced_once = True
            except Exception as exc:
                logger.error("首次配置同步失败", extra={"extra_fields": {"error": str(exc)}})

        # 订阅实时数据（重连同样重订阅）
        if self._subscribe_data:
            await self.client.online_data_subscribe(True)
            logger.info("已订阅实时数据推送")
        # 订阅设备级告警（重连同样重订阅）
        if self._subscribe_alarm:
            await self.client.online_alarm_subscribe(True)
            logger.info("已订阅告警推送")

        await self._heart_loop()

    async def _heart_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_interval)
                return  # stop 被触发
            except TimeoutError:
                pass
            # 心跳失败 / error_code 2/106 → 抛出由主循环重连
            try:
                await self.client.heart()
            except Exception as exc:
                # 审查 M8：心跳是 EMS 在线性核心探针，失败应有独立指标，便于区分「心跳超时」
                # 与「连接被对端断开」（此前只有笼统的 ems_offline）。记录后仍抛出由主循环重连。
                await record_failure(M_EMS_HEARTBEAT, error=str(exc))
                raise
            await redis_client.hset(REDIS_EMS_CONN, "last_heart", int(time.time()))

    # ---- 状态写入 ----
    async def _set_state(
        self,
        state: str,
        *,
        token_ok: str | None = None,
        last_heart: int | None = None,
    ) -> None:
        # Redis 哈希值统一以字符串存储；读取侧再按需解析为 int/bool
        mapping: dict[str, str] = {"state": state, "reconnects": str(self._reconnects)}
        if token_ok is not None:
            mapping["token_ok"] = token_ok
        if last_heart is not None:
            mapping["last_heart"] = str(last_heart)
        try:
            # type: ignore[arg-type] — redis-py 存根对 mapping 的 TypeVar 不变性限制，dict[str,str] 运行期合法
            await redis_client.hset(REDIS_EMS_CONN, mapping=mapping)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("写连接状态失败", extra={"extra_fields": {"error": str(exc)}})

    # ---- 手动触发同步（供 API 调用）----
    async def manual_sync(self) -> SyncResult:
        if not self.client.token:
            raise EmsError(2, "EMS 未连接，无法同步")
        return await run_config_sync(self.client, batch_size=settings.ems_sync_batch_size)


# ---- 模块级单例 ----
_manager: ConnectionManager | None = None


def get_manager() -> ConnectionManager | None:
    return _manager


async def _build_manager_from_db() -> ConnectionManager | None:
    """从 ems_config 读取配置（解密密码）构建连接管理。"""
    async with AsyncSessionLocal() as db:
        cfg = await db.get(EmsConfig, 1)
        if cfg is None:
            logger.warning("未找到 ems_config，跳过连接管理启动")
            return None
        password = decrypt(cfg.password_enc)
        return ConnectionManager(
            base_url=cfg.base_url,
            version=cfg.version_str,
            username=cfg.username,
            password=password,
            recv_ip=cfg.recv_ip,
            recv_port=cfg.recv_port,
            subscribe_data=cfg.subscribe_data,
            subscribe_alarm=cfg.subscribe_alarm,
        )


async def start_connection_manager() -> None:
    global _manager
    if _manager is not None:
        return
    _manager = await _build_manager_from_db()
    if _manager is not None:
        await _manager.start()


async def stop_connection_manager() -> None:
    global _manager
    if _manager is not None:
        await _manager.stop()
        _manager = None


async def restart_connection_manager() -> None:
    """配置变更后重启连接（PUT /settings/ems 调用）。"""
    await stop_connection_manager()
    await start_connection_manager()
