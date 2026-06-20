"""SQLAlchemy ORM 模型。

注意：数据库结构以 Alembic 迁移（02 的 DDL）为事实源；
ORM 模型按需逐 Sprint 补充。
"""
from app.models.alarm import Alarm, AlarmEvent, AlarmRule
from app.models.asset import Device, DeviceStatus, Point, Space
from app.models.meta import AssetMeta
from app.models.notify import (
    NotifyChannel,
    NotifyLog,
    NotifyRoute,
    Recipient,
    RecipientGroup,
    RecipientGroupMember,
)
from app.models.suppress import MaintenanceWindow, PointMute
from app.models.system import EmsConfig, ReportSchedule, SyncLog
from app.models.user import User

__all__ = [
    "User",
    "Space",
    "Device",
    "Point",
    "DeviceStatus",
    "EmsConfig",
    "SyncLog",
    "ReportSchedule",
    "AlarmRule",
    "Alarm",
    "AlarmEvent",
    "AssetMeta",
    "PointMute",
    "MaintenanceWindow",
    "NotifyChannel",
    "Recipient",
    "RecipientGroup",
    "RecipientGroupMember",
    "NotifyRoute",
    "NotifyLog",
]
