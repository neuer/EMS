"""抑制 DB 谓词测试（审查 E5）。

maintenance_silenced 的「任一 record_silenced=True 即记录、全 False 则丢弃」聚合，与
is_muted、_resolve_scope_ids 的点→设备→空间解析，此前在相关测试里被 _no_suppress 桩空。
因 MaintenanceWindow/PointMute 含 PG ARRAY，此处用桩 DB 行单测谓词逻辑（不进内存库）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from app.core.constants import (
    RESOURCE_KIND_DEVICE,
    RESOURCE_KIND_POINT,
    RESOURCE_KIND_SPACE,
)
from app.engine import suppress
from sqlalchemy.ext.asyncio import AsyncSession

_NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
_PAST = _NOW - timedelta(hours=1)
_FUTURE = _NOW + timedelta(hours=1)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _RowsDB:
    """桩 DB：execute() 恒返回预置行；get() 按 (模型名, id) 命中。"""

    def __init__(
        self,
        rows: list[Any] | None = None,
        objs: dict[tuple[str, str], Any] | None = None,
    ) -> None:
        self._rows = rows or []
        self._objs = objs or {}

    async def execute(self, *_a, **_k) -> _Result:
        return _Result(self._rows)

    async def get(self, model: Any, oid: str) -> Any:
        return self._objs.get((model.__name__, oid))


def _db(rows=None, objs=None) -> AsyncSession:
    return cast(AsyncSession, _RowsDB(rows=rows, objs=objs))


async def _silenced(db: AsyncSession) -> tuple[bool, bool]:
    return await suppress.maintenance_silenced(db, "p1", RESOURCE_KIND_POINT, _NOW)


def _stub_scope(monkeypatch) -> None:
    async def _scope(*_a, **_k):
        return {RESOURCE_KIND_POINT: "p1"}

    monkeypatch.setattr(suppress, "_resolve_scope_ids", _scope)


# ---- maintenance_silenced 聚合 ----
async def test_maintenance_record_true_silences_and_records(monkeypatch):
    _stub_scope(monkeypatch)
    silenced, should_record = await _silenced(
        _db(rows=[(RESOURCE_KIND_POINT, ["p1"], _PAST, _FUTURE, True)])
    )
    assert silenced is True
    assert should_record is True


async def test_maintenance_any_record_true_wins(monkeypatch):
    _stub_scope(monkeypatch)
    silenced, should_record = await _silenced(_db(rows=[
        (RESOURCE_KIND_POINT, ["p1"], _PAST, _FUTURE, False),
        (RESOURCE_KIND_POINT, ["p1"], _PAST, _FUTURE, True),
    ]))
    assert silenced is True
    assert should_record is True  # 任一 record=True 即记录


async def test_maintenance_all_record_false_drops(monkeypatch):
    _stub_scope(monkeypatch)
    silenced, should_record = await _silenced(
        _db(rows=[(RESOURCE_KIND_POINT, ["p1"], _PAST, _FUTURE, False)])
    )
    assert silenced is True
    assert should_record is False  # 全 False → 应丢弃（raise_alarm 据此 return None）


async def test_maintenance_out_of_window_not_silenced(monkeypatch):
    _stub_scope(monkeypatch)
    silenced, should_record = await _silenced(
        _db(rows=[(RESOURCE_KIND_POINT, ["p1"], _FUTURE, None, True)])  # 窗口未开始
    )
    assert silenced is False
    assert should_record is False


async def test_maintenance_scope_mismatch_not_silenced(monkeypatch):
    _stub_scope(monkeypatch)
    silenced, _ = await _silenced(
        _db(rows=[(RESOURCE_KIND_POINT, ["other"], _PAST, _FUTURE, True)])  # id 不在范围内
    )
    assert silenced is False


# ---- is_muted ----
async def test_is_muted_true_within_window():
    assert await suppress.is_muted(_db(rows=[(_PAST, _FUTURE)]), "p1", _NOW) is True


async def test_is_muted_false_when_expired():
    assert await suppress.is_muted(_db(rows=[(_PAST, _PAST)]), "p1", _NOW) is False


async def test_is_muted_open_ended_null_end():
    # end 为 NULL → 长期屏蔽
    assert await suppress.is_muted(_db(rows=[(_PAST, None)]), "p1", _NOW) is True


# ---- _resolve_scope_ids 点→设备→空间 ----
async def test_resolve_scope_point_to_device_to_space():
    objs = {
        ("Point", "p1"): SimpleNamespace(device_id="d1"),
        ("Device", "d1"): SimpleNamespace(parent_id="s1"),
    }
    cand = await suppress._resolve_scope_ids(_db(objs=objs), "p1", RESOURCE_KIND_POINT)
    assert cand[RESOURCE_KIND_POINT] == "p1"
    assert cand[RESOURCE_KIND_DEVICE] == "d1"
    assert cand[RESOURCE_KIND_SPACE] == "s1"


async def test_resolve_scope_device_entry_to_space():
    """device 入口分支：解析到自身设备与其父空间。"""
    objs = {("Device", "d1"): SimpleNamespace(parent_id="s1")}
    cand = await suppress._resolve_scope_ids(_db(objs=objs), "d1", RESOURCE_KIND_DEVICE)
    assert cand[RESOURCE_KIND_DEVICE] == "d1"
    assert cand[RESOURCE_KIND_SPACE] == "s1"


async def test_resolve_scope_device_without_parent_short_circuits():
    """dev.parent_id 为空 → 不解析空间维度（短路分支）。"""
    objs = {("Device", "d1"): SimpleNamespace(parent_id=None)}
    cand = await suppress._resolve_scope_ids(_db(objs=objs), "d1", RESOURCE_KIND_DEVICE)
    assert cand[RESOURCE_KIND_DEVICE] == "d1"
    assert RESOURCE_KIND_SPACE not in cand
