"""断连回补编排测试（审查 I1 + 红线 #5 锁串行）。

用 fake_redis（历史锁）+ 桩 DB 会话/客户端，验证：
- 历史锁被占用 → 跳过且不发起任何 offline_value 调用（红线 #5）。
- 传输类失败 → 计入 failed_slices（缺口应保留待重试）。
- EmsError（如 101 坏 ID）→ 跳过但不计 failed_slices（不阻塞缺口清除）。
"""
from __future__ import annotations

import pytest
from app.core.constants import REDIS_HISTORY_LOCK
from app.ems.protocol import EmsError
from app.history import backfill


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def add(self, _obj):
        pass

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def execute(self, *_a, **_k):
        return None


class _Client:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = 0

    async def offline_value(self, start, end, ids, interval):
        self.calls += 1
        if self.behavior == "ems_error":
            raise EmsError(101, "resource not exist")
        if self.behavior == "transport":
            raise RuntimeError("connect timeout")
        return [{"resource_id": ids[0], "data_list": [{"value": "1", "time": str(start)}]}]


@pytest.fixture
def _stub_db(monkeypatch):
    monkeypatch.setattr(backfill, "AsyncSessionLocal", lambda: _FakeSession())

    async def _noop_cagg(_s, _e):
        return None

    monkeypatch.setattr(backfill, "_refresh_cagg", _noop_cagg)


async def test_lock_held_skips_without_calling_ems(fake_redis, _stub_db):
    await fake_redis.set(REDIS_HISTORY_LOCK, "other")  # 已有历史请求在跑
    client = _Client("ok")
    result = await backfill.run_backfill(client, ["p1"], 1000, 2000)  # type: ignore[arg-type]
    assert result.skipped is True
    assert result.reason == "locked"
    assert client.calls == 0  # 红线 #5：未发起任何 offline_value


async def test_transport_failure_counts_failed_slice(fake_redis, _stub_db):
    client = _Client("transport")
    result = await backfill.run_backfill(client, ["p1"], 1000, 2000)  # type: ignore[arg-type]
    assert result.failed_slices == 1  # 可重试失败 → 缺口应保留
    assert result.points == 0
    assert await fake_redis.get(REDIS_HISTORY_LOCK) is None  # 锁已释放


async def test_ems_error_skips_without_failed_slice(fake_redis, _stub_db):
    client = _Client("ems_error")
    result = await backfill.run_backfill(client, ["p1"], 1000, 2000)  # type: ignore[arg-type]
    assert result.failed_slices == 0  # 坏 ID 不计可重试失败，不阻塞缺口清除
    assert result.points == 0


async def test_success_persists_and_releases_lock(fake_redis, _stub_db):
    client = _Client("ok")
    result = await backfill.run_backfill(client, ["p1"], 1000, 2000)  # type: ignore[arg-type]
    assert result.failed_slices == 0
    assert result.batches == 1
    assert await fake_redis.get(REDIS_HISTORY_LOCK) is None
