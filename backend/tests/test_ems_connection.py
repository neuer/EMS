"""EMS 连接生命周期行为测试（红线 #4，审查 E1）。

此前 connection.py 的 _run/_connect_cycle/_heart_loop 零行为覆盖。此处用注入式桩 client
离线验证：重订阅 data+alarm、心跳失败触发重连重订阅、凭据致命错误停止重连、退避不真实 sleep。
"""
from __future__ import annotations

import asyncio

import pytest
from app.core.constants import CONN_STATE_OFFLINE, REDIS_EMS_CONN
from app.ems import connection
from app.ems.protocol import EmsError


class _StubClient:
    """记录调用次数的桩 EMS client；可编程 login/heart 抛错。"""

    def __init__(self, *, login_error=None, heart_error=None, on_login=None) -> None:
        self.token: str | None = "tok"
        self.login_count = 0
        self.data_sub_count = 0
        self.alarm_sub_count = 0
        self.heart_count = 0
        self._login_error = login_error
        self._heart_error = heart_error
        self._on_login = on_login

    async def login(self, *_a, **_k) -> str:
        self.login_count += 1
        if self._on_login is not None:
            self._on_login(self)
        if self._login_error is not None:
            raise self._login_error
        self.token = "tok"
        return "tok"

    async def online_data_subscribe(self, _v: bool = True) -> None:
        self.data_sub_count += 1

    async def online_alarm_subscribe(self, _v: bool = True) -> None:
        self.alarm_sub_count += 1

    async def heart(self) -> None:
        self.heart_count += 1
        if self._heart_error is not None:
            raise self._heart_error

    async def logout(self) -> None:
        self.token = None

    async def aclose(self) -> None:
        return None


def _make_manager() -> connection.ConnectionManager:
    mgr = connection.ConnectionManager(
        base_url="http://ems", version="v1", username="u", password="p",
        recv_ip="backend", recv_port="8000", subscribe_data=True, subscribe_alarm=True,
    )
    mgr._synced_once = True  # 跳过首连配置同步（避免依赖 DB/EMS）
    mgr.heartbeat_interval = 0  # 心跳等待立即超时，不真实 sleep
    return mgr


async def test_protocol_error_classification() -> None:
    """红线 #4：2/106 需重登；100 为致命停止。"""
    assert EmsError(2, "abnormal token").need_relogin
    assert EmsError(106, "heart timeout").need_relogin
    assert EmsError(100, "bad cred").is_fatal
    assert not EmsError(101, "no resource").is_fatal


async def test_connect_cycle_resubscribes_data_and_alarm(fake_redis) -> None:
    """_connect_cycle 成功后必须同时重订阅 data 与 alarm（红线 #4）。"""
    mgr = _make_manager()
    mgr.client = _StubClient()  # type: ignore[assignment]
    mgr._stop.set()  # 使 _heart_loop 进入即返回，不进心跳循环
    await mgr._connect_cycle()
    stub = mgr.client
    assert stub.login_count == 1  # type: ignore[attr-defined]
    assert stub.data_sub_count == 1  # type: ignore[attr-defined]
    assert stub.alarm_sub_count == 1  # type: ignore[attr-defined]


async def test_heart_failure_propagates_relogin(fake_redis) -> None:
    """心跳抛 error_code 2 → 冒泡（由 _run 捕获重连），且属需重登。"""
    mgr = _make_manager()
    mgr.client = _StubClient(heart_error=EmsError(2, "abnormal token"))  # type: ignore[assignment]
    with pytest.raises(EmsError) as ei:
        await mgr._heart_loop()
    assert ei.value.need_relogin


async def test_run_reconnects_and_resubscribes_after_heart_failure(fake_redis) -> None:
    """心跳失败后 _run 重连并再次重订阅 data+alarm；max_backoff=0 使退避不真实 sleep。"""
    mgr = _make_manager()
    mgr.max_backoff = 0  # delay=min(backoff,0)=0，退避等待立即超时

    def _stop_after_two(stub: _StubClient) -> None:
        if stub.login_count >= 2:
            mgr._stop.set()

    mgr.client = _StubClient(  # type: ignore[assignment]
        heart_error=EmsError(2, "abnormal token"), on_login=_stop_after_two
    )
    await asyncio.wait_for(mgr._run(), timeout=2)
    stub = mgr.client
    assert stub.login_count == 2  # type: ignore[attr-defined]  恰好重连一次（stop 后不多跑）
    assert stub.data_sub_count == 2  # type: ignore[attr-defined]  每次重连都重订阅 data
    assert stub.alarm_sub_count == 2  # type: ignore[attr-defined]  每次重连都重订阅 alarm


async def test_run_stops_on_fatal_credential_error(fake_redis) -> None:
    """凭据错误（100）为致命 → _run 立即停止且不重连。"""
    mgr = _make_manager()
    mgr.client = _StubClient(login_error=EmsError(100, "bad cred"))  # type: ignore[assignment]
    await asyncio.wait_for(mgr._run(), timeout=2)
    assert mgr.client.login_count == 1  # type: ignore[attr-defined]  未重连
    # 区分「致命 break 退出」与「正常 stop 退出」：致命路径不应触发 _stop
    assert mgr._stop.is_set() is False
    # 致命退出前写入离线状态 token_ok=0（红线 #10.1 可观测）
    assert await fake_redis.hget(REDIS_EMS_CONN, "state") == CONN_STATE_OFFLINE
    assert await fake_redis.hget(REDIS_EMS_CONN, "token_ok") == "0"
