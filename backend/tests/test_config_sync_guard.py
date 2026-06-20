"""配置同步失活保护测试（审查 I5）。

本次全量为空（疑似 EMS 瞬时故障返回 []）且库内仍有 active → 跳过失活，不清空资产树。
用桩 db 验证「空 incoming + 有 active」时不发起 update。
"""
from __future__ import annotations

from app.models.asset import Space
from app.sync.config_sync import _upsert


class _Scalars:
    def __init__(self, vals):
        self._v = vals

    def all(self):
        return self._v


class _Result:
    def __init__(self, vals):
        self._v = vals

    def scalars(self):
        return _Scalars(self._v)


class _FakeDB:
    def __init__(self, active):
        self.active = active
        self.execute_calls = 0

    async def execute(self, _stmt):
        self.execute_calls += 1
        return _Result(self.active)


async def test_empty_incoming_skips_deactivation_when_active_exists():
    db = _FakeDB(active=["s1", "s2", "s3"])
    result = await _upsert(db, Space, [], set())  # type: ignore[arg-type]
    assert result.inactivated == 0
    # 仅一次 execute（stale 查询）；未发起 update 失活
    assert db.execute_calls == 1


async def test_empty_incoming_no_active_is_noop():
    db = _FakeDB(active=[])
    result = await _upsert(db, Space, [], set())  # type: ignore[arg-type]
    assert result.inactivated == 0
