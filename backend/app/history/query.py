"""历史趋势查询：按范围自动选层（红线 #6）。

- 原始层 `point_history`（30 天）：短范围、需要原始精度时使用。
- 降采样层 `point_history_5min`（连续聚合，6 个月）：长范围使用，按 5min 桶聚合。
- auto：跨度 ≤ HISTORY_RAW_MAX_SPAN_S 走原始层，否则走 5min。

查询入口为本地 DB（不调用 EMS），与回补的 offline_value 串行限制无关。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import HISTORY_RAW_MAX_SPAN_S
from app.schemas.history import AggSample, HistoryResult, HistorySeries, RawSample


def select_layer(start: int, end: int, agg: str) -> Literal["raw", "5min"]:
    """选层纯函数：返回 'raw' 或 '5min'。

    agg 为 raw/5min 时直接采用；auto 时按跨度阈值判定。
    """
    if agg == "raw":
        return "raw"
    if agg == "5min":
        return "5min"
    # auto
    span = max(0, end - start)
    return "raw" if span <= HISTORY_RAW_MAX_SPAN_S else "5min"


def _utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


_RAW_SQL = text(
    "SELECT point_id, ts, value FROM point_history "
    "WHERE point_id = ANY(:ids) AND ts >= :start AND ts <= :end "
    "ORDER BY point_id, ts"
)

_AGG_SQL = text(
    "SELECT point_id, bucket, avg_value, min_value, max_value, sample_count "
    "FROM point_history_5min "
    "WHERE point_id = ANY(:ids) AND bucket >= :start AND bucket <= :end "
    "ORDER BY point_id, bucket"
)


async def query_history(
    db: AsyncSession, point_ids: list[str], start: int, end: int, agg: str
) -> HistoryResult:
    """执行历史查询，返回结构化序列。"""
    layer = select_layer(start, end, agg)
    params = {"ids": point_ids, "start": _utc(start), "end": _utc(end)}

    # 预置空序列，保证每个测点都有返回（空值键保留）
    if layer == "raw":
        buckets: dict[str, list[RawSample]] = {pid: [] for pid in point_ids}
        rows = (await db.execute(_RAW_SQL, params)).all()
        for pid, ts, value in rows:
            buckets[pid].append(RawSample(ts=_epoch(ts), value=value))
        series = [
            HistorySeries(point_id=pid, layer="raw", raw=buckets[pid]) for pid in point_ids
        ]
    else:
        agg_buckets: dict[str, list[AggSample]] = {pid: [] for pid in point_ids}
        rows = (await db.execute(_AGG_SQL, params)).all()
        for pid, bucket, avg_v, min_v, max_v, cnt in rows:
            agg_buckets[pid].append(
                AggSample(
                    ts=_epoch(bucket),
                    avg=avg_v,
                    min=min_v,
                    max=max_v,
                    count=int(cnt or 0),
                )
            )
        series = [
            HistorySeries(point_id=pid, layer="5min", agg=agg_buckets[pid])
            for pid in point_ids
        ]

    return HistoryResult(layer=layer, start=start, end=end, series=series)
