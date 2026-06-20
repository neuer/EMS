"""测试共享夹具（红线 #9.3：离线、无外网、无密钥、确定性）。

- fake_redis：内存态 Redis（fakeredis），patch 全部已加载 app.* 模块的 redis_client 引用。
- mem_db：内存态 SQLAlchemy 异步引擎（aiosqlite），仅建告警相关表（标准类型，sqlite 兼容），
  patch 各模块的 AsyncSessionLocal 引用，供 engine/lifecycle/alarm 行为测试使用。

含 PG 专有类型（ARRAY/JSONB）的 notify/suppress 模型不在内存库建表，相关测试改用桩。
"""
from __future__ import annotations

import sys

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


# sqlite 只对 INTEGER PRIMARY KEY 自增；把 BigInteger 在 sqlite 方言下渲染为 INTEGER，
# 使 BigInteger 自增主键（alarms/alarm_rules 等）在内存库可用。仅影响测试方言。
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN202
    return "INTEGER"


def _patch_attr_everywhere(monkeypatch: pytest.MonkeyPatch, attr: str, value: object) -> None:
    """把名为 attr 的模块级引用，在所有已加载 app.* 模块上替换为 value。

    模块普遍以 `from app.core.x import attr` 绑定了本地名，必须逐处 setattr 才能生效。
    """
    for name, mod in list(sys.modules.items()):
        if name.startswith("app.") and hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, value, raising=False)


@pytest_asyncio.fixture
async def fake_redis(monkeypatch: pytest.MonkeyPatch):
    """内存态 Redis；替换全局与各模块引用。用完 flush。"""
    from fakeredis import aioredis as fake_aioredis

    client = fake_aioredis.FakeRedis(decode_responses=True)
    import app.core.redis as redis_mod

    monkeypatch.setattr(redis_mod, "redis_client", client)
    _patch_attr_everywhere(monkeypatch, "redis_client", client)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest_asyncio.fixture
async def mem_db(monkeypatch: pytest.MonkeyPatch):
    """内存态告警库；返回 async_sessionmaker，并 patch 各模块 AsyncSessionLocal。"""
    from app.core.db import Base
    from app.models.alarm import Alarm, AlarmEvent, AlarmRule  # noqa: F401  确保表已注册
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    alarm_tables = [
        Base.metadata.tables[name]
        for name in (AlarmRule.__tablename__, Alarm.__tablename__, AlarmEvent.__tablename__)
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=alarm_tables)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    import app.core.db as db_mod

    monkeypatch.setattr(db_mod, "AsyncSessionLocal", sessionmaker)
    _patch_attr_everywhere(monkeypatch, "AsyncSessionLocal", sessionmaker)
    try:
        yield sessionmaker
    finally:
        await engine.dispose()
