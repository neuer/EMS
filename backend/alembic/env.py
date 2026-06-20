"""Alembic 环境。

要点：
- 连接串来自应用 settings（同步驱动 psycopg2）。
- 使用 AUTOCOMMIT 隔离级别运行迁移：TimescaleDB 的连续聚合
  (CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)) 不允许在事务块内执行，
  故整个迁移以 autocommit 运行。greenfield 单初始迁移，可接受非原子性。
"""
from __future__ import annotations

from logging.config import fileConfig

# 导入模型以便 autogenerate（当前 Sprint 仅 User，结构以手写 DDL 为准）
import app.models  # noqa: F401
from alembic import context
from app.core.config import settings
from app.core.db import Base
from sqlalchemy import create_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        settings.database_url_sync,
        isolation_level="AUTOCOMMIT",
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # autocommit 模式下不再额外包事务
            transactional_ddl=False,
        )
        context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
