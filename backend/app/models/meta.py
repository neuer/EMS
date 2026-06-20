"""元数据增强 ORM：asset_meta（平台侧叠加，不污染 EMS 同步源，红线 #8）。

映射 02 DDL 的 asset_meta；结构以迁移 0001 为事实源。按 resource_id 关联空间/设备/测点。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AssetMeta(Base):
    __tablename__ = "asset_meta"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 5空间 2设备 3测点
    alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    importance: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1-5
    custom_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
