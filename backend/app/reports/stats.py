"""告警统计聚合（日 / 周 / 月）。

设计：纯函数 `aggregate_alarms` 负责全部聚合逻辑（可离线确定性单测），
异步 `load_alarm_stats` 仅负责取数并调用纯函数 + 解析 Top 资源名。

时间口径（红线 #10）：alarms.triggered_at 为 TIMESTAMPTZ(UTC)，
分桶按展示时区（settings.timezone，默认 Asia/Shanghai）换算到本地日历。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.alarm import Alarm
from app.models.asset import Device, Point, Space

TOP_RESOURCE_LIMIT = 10


@dataclass(frozen=True)
class AlarmRow:
    """聚合输入的规范化告警行（与 ORM 解耦，便于离线构造测试数据）。"""

    triggered_at: datetime
    level: int
    source: str
    resource_id: str
    event_type: int | None = None
    accepted_at: datetime | None = None
    recovered_at: datetime | None = None


@dataclass
class StatsBucket:
    bucket: str
    total: int = 0
    by_level: Counter[int] = field(default_factory=Counter)
    by_source: Counter[str] = field(default_factory=Counter)


@dataclass
class StatsResult:
    granularity: str
    start: int
    end: int
    total: int
    by_level: dict[int, int]
    by_source: dict[str, int]
    by_event_type: dict[int, int]
    buckets: list[StatsBucket]
    top_resources: list[tuple[str, int]]
    mtta_seconds: float | None
    mttr_seconds: float | None


def bucket_label(dt_local: datetime, granularity: str) -> str:
    """根据本地时间与粒度生成稳定桶标签。"""
    if granularity == "day":
        return dt_local.strftime("%Y-%m-%d")
    if granularity == "week":
        iso = dt_local.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if granularity == "month":
        return dt_local.strftime("%Y-%m")
    raise ValueError(f"未知粒度: {granularity}")


def _avg_seconds(deltas: list[float]) -> float | None:
    return round(sum(deltas) / len(deltas), 1) if deltas else None


def aggregate_alarms(
    rows: list[AlarmRow], granularity: str, start: int, end: int, tz: ZoneInfo
) -> StatsResult:
    """纯聚合：返回总量、分级/来源/事件类型分布、按桶时间线、Top 资源、MTTA/MTTR。"""
    by_level: Counter[int] = Counter()
    by_source: Counter[str] = Counter()
    by_event_type: Counter[int] = Counter()
    by_resource: Counter[str] = Counter()
    buckets: dict[str, StatsBucket] = {}
    bucket_order: list[str] = []
    mtta: list[float] = []
    mttr: list[float] = []

    for r in rows:
        by_level[r.level] += 1
        by_source[r.source] += 1
        if r.event_type is not None:
            by_event_type[r.event_type] += 1
        by_resource[r.resource_id] += 1

        local = r.triggered_at.astimezone(tz)
        label = bucket_label(local, granularity)
        b = buckets.get(label)
        if b is None:
            b = StatsBucket(bucket=label)
            buckets[label] = b
            bucket_order.append(label)
        b.total += 1
        b.by_level[r.level] += 1
        b.by_source[r.source] += 1

        if r.accepted_at is not None:
            mtta.append((r.accepted_at - r.triggered_at).total_seconds())
        if r.recovered_at is not None:
            mttr.append((r.recovered_at - r.triggered_at).total_seconds())

    ordered = [buckets[label] for label in sorted(bucket_order)]
    top = by_resource.most_common(TOP_RESOURCE_LIMIT)

    return StatsResult(
        granularity=granularity,
        start=start,
        end=end,
        total=len(rows),
        by_level=dict(by_level),
        by_source=dict(by_source),
        by_event_type=dict(by_event_type),
        buckets=ordered,
        top_resources=top,
        mtta_seconds=_avg_seconds(mtta),
        mttr_seconds=_avg_seconds(mttr),
    )


async def _resolve_names(db: AsyncSession, resource_ids: list[str]) -> dict[str, str]:
    """解析资源 id → 名称（测点/设备/空间镜像，只读）。"""
    if not resource_ids:
        return {}
    names: dict[str, str] = {}
    for model in (Point, Device, Space):
        rows = (
            await db.execute(
                select(model.resource_id, model.name).where(
                    model.resource_id.in_(resource_ids)
                )
            )
        ).all()
        for rid, name in rows:
            names.setdefault(rid, name)
    return names


async def load_alarm_stats(
    db: AsyncSession, start: int, end: int, granularity: str
) -> tuple[StatsResult, dict[str, str]]:
    """取 [start, end] 内告警并聚合；返回 (统计结果, Top 资源名映射)。"""
    tz = ZoneInfo(settings.timezone)
    start_dt = datetime.fromtimestamp(start, tz=UTC)
    end_dt = datetime.fromtimestamp(end, tz=UTC)
    orm_rows = (
        await db.execute(
            select(Alarm).where(
                Alarm.triggered_at >= start_dt, Alarm.triggered_at <= end_dt
            )
        )
    ).scalars().all()
    rows = [
        AlarmRow(
            triggered_at=a.triggered_at,
            level=a.level,
            source=a.source,
            resource_id=a.resource_id,
            event_type=a.event_type,
            accepted_at=a.accepted_at,
            recovered_at=a.recovered_at,
        )
        for a in orm_rows
    ]
    result = aggregate_alarms(rows, granularity, start, end, tz)
    names = await _resolve_names(db, [rid for rid, _ in result.top_resources])
    return result, names
