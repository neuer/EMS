"""数据 / 告警导出（CSV / Excel）。

纯函数 `build_csv` / `build_xlsx` 负责字节构造（可离线单测）；
异步 loader 负责取数并整形为 (表头, 行)。
历史数据导出复用 `history.query.query_history`，确保「按范围选层」（红线 #6）逻辑单点维护。
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.history.query import query_history
from app.models.alarm import Alarm
from app.models.asset import Point

LEVEL_NAME = {1: "紧急", 2: "严重", 3: "重要", 4: "次要", 5: "提示"}


def build_csv(headers: list[str], rows: list[list[Any]]) -> bytes:
    """构造 UTF-8(BOM) CSV 字节，便于 Excel 直接打开不乱码。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def build_xlsx(headers: list[str], rows: list[list[Any]], sheet_name: str = "Sheet1") -> bytes:
    """构造 Excel(xlsx) 字节（openpyxl，内存生成）。"""
    wb = Workbook()
    ws = wb.active
    if ws is None:  # 新建 Workbook 必有活动表，此处仅为类型收窄
        ws = wb.create_sheet()
    ws.title = sheet_name[:31] or "Sheet1"
    ws.append(headers)
    for row in rows:
        ws.append(["" if v is None else v for v in row])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _local_iso(dt: datetime | None, tz: ZoneInfo) -> str | None:
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") if dt else None


# ---- 告警导出 ----
ALARM_HEADERS = [
    "ID", "级别", "级别名", "来源", "资源", "事件类型", "状态", "触发值",
    "内容", "合并次数", "触发时间", "受理时间", "确认时间", "恢复时间",
]


async def load_alarm_rows(
    db: AsyncSession,
    start: int,
    end: int,
    level: int | None = None,
    source: str | None = None,
) -> tuple[list[str], list[list[Any]]]:
    tz = ZoneInfo(settings.timezone)
    stmt = select(Alarm).where(
        Alarm.triggered_at >= datetime.fromtimestamp(start, tz=UTC),
        Alarm.triggered_at <= datetime.fromtimestamp(end, tz=UTC),
    )
    if level is not None:
        stmt = stmt.where(Alarm.level == level)
    if source is not None:
        stmt = stmt.where(Alarm.source == source)
    stmt = stmt.order_by(Alarm.triggered_at.desc())
    alarms = (await db.execute(stmt)).scalars().all()
    rows = [
        [
            a.id, a.level, LEVEL_NAME.get(a.level, "?"), a.source, a.resource_id,
            a.event_type, a.status, a.trigger_value, a.content, a.merge_count,
            _local_iso(a.triggered_at, tz), _local_iso(a.accepted_at, tz),
            _local_iso(a.confirmed_at, tz), _local_iso(a.recovered_at, tz),
        ]
        for a in alarms
    ]
    return ALARM_HEADERS, rows


# ---- 历史数据导出 ----
async def load_history_rows(
    db: AsyncSession, point_ids: list[str], start: int, end: int, agg: str
) -> tuple[list[str], list[list[Any]]]:
    tz = ZoneInfo(settings.timezone)
    name_rows = (
        await db.execute(
            select(Point.resource_id, Point.name).where(Point.resource_id.in_(point_ids))
        )
    ).all()
    names = {rid: name for rid, name in name_rows}
    result = await query_history(db, point_ids, start, end, agg)

    def fmt(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=UTC).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

    if result.layer == "raw":
        headers = ["测点", "名称", "时间", "数值"]
        rows: list[list[Any]] = []
        for s in result.series:
            for p in s.raw or []:
                rows.append([s.point_id, names.get(s.point_id, ""), fmt(p.ts), p.value])
        return headers, rows

    headers = ["测点", "名称", "时间(5min桶)", "均值", "最小", "最大", "样本数"]
    rows = []
    for s in result.series:
        for p in s.agg or []:
            rows.append(
                [s.point_id, names.get(s.point_id, ""), fmt(p.ts), p.avg, p.min, p.max, p.count]
            )
    return headers, rows
