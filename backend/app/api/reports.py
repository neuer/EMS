"""报表 API（A6）：告警统计（日/周/月）+ 数据/告警导出（CSV/Excel）+ 定时报表计划。

只读统计与导出对所有登录角色开放（报表为只读产物）；
报表计划属系统配置，限管理员；run-now 立即生成并发送一次。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_idempotency, require_role
from app.core.config import settings
from app.core.db import get_db
from app.core.security import Role
from app.models.system import ReportSchedule
from app.models.user import User
from app.reports.export import build_csv, build_xlsx, load_alarm_rows, load_history_rows
from app.reports.service import run_report_schedule
from app.reports.stats import load_alarm_stats
from app.scheduler import reload_report_jobs, report_next_runs
from app.schemas.common import ok
from app.schemas.history import HistoryQuery
from app.schemas.report import (
    AlarmStatsResult,
    ExportFormat,
    Granularity,
    ReportScheduleInput,
    ReportScheduleOutput,
    ReportScheduleUpdate,
    StatBucket,
    TopResource,
)

router = APIRouter(prefix="/reports", tags=["报表"])

_CSV_MIME = "text/csv; charset=utf-8"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------- 告警统计 ----------------
@router.get("/alarm-stats")
async def alarm_stats(
    start: int = Query(..., description="起始 Unix 秒"),
    end: int = Query(..., description="结束 Unix 秒"),
    granularity: Granularity = Query("day"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    if end <= start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end 必须大于 start")
    result, names = await load_alarm_stats(db, start, end, granularity)
    out = AlarmStatsResult(
        granularity=granularity,
        start=result.start,
        end=result.end,
        total=result.total,
        by_level=result.by_level,
        by_source=result.by_source,
        by_event_type=result.by_event_type,
        buckets=[
            StatBucket(
                bucket=b.bucket, total=b.total,
                by_level=dict(b.by_level), by_source=dict(b.by_source),
            )
            for b in result.buckets
        ],
        top_resources=[
            TopResource(resource_id=rid, name=names.get(rid), count=cnt)
            for rid, cnt in result.top_resources
        ],
        mtta_seconds=result.mtta_seconds,
        mttr_seconds=result.mttr_seconds,
    )
    return ok(out.model_dump())


# ---------------- 导出 ----------------
def _file_response(data: bytes, filename: str, fmt: str) -> Response:
    mime = _XLSX_MIME if fmt == "xlsx" else _CSV_MIME
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/alarms")
async def export_alarms(
    start: int = Query(...),
    end: int = Query(...),
    fmt: ExportFormat = Query("csv"),
    level: int | None = Query(None, ge=1, le=5),
    source: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    headers, rows = await load_alarm_rows(db, start, end, level=level, source=source)
    ts = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        return _file_response(build_xlsx(headers, rows, "告警"), f"alarms_{ts}.xlsx", fmt)
    return _file_response(build_csv(headers, rows), f"alarms_{ts}.csv", fmt)


@router.post("/export/history")
async def export_history(
    body: HistoryQuery,
    fmt: ExportFormat = Query("csv"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    headers, rows = await load_history_rows(db, body.point_ids, body.start, body.end, body.agg)
    ts = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        return _file_response(build_xlsx(headers, rows, "历史数据"), f"history_{ts}.xlsx", fmt)
    return _file_response(build_csv(headers, rows), f"history_{ts}.csv", fmt)


# ---------------- 定时报表计划 ----------------
def _schedule_dump(s: ReportSchedule, next_runs: dict[int, datetime]) -> dict[str, object]:
    nr = next_runs.get(s.id)
    return ReportScheduleOutput(
        id=s.id, name=s.name, report_type=s.report_type, cron=s.cron,
        group_ids=list(s.group_ids or []), enabled=s.enabled,
        next_run=nr.strftime("%Y-%m-%d %H:%M:%S") if nr else None,
    ).model_dump()


@router.get("/schedules")
async def list_schedules(
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rows = (await db.execute(select(ReportSchedule).order_by(ReportSchedule.id))).scalars().all()
    next_runs = report_next_runs()
    return ok([_schedule_dump(s, next_runs) for s in rows])


@router.post("/schedules")
async def create_schedule(
    body: ReportScheduleInput,
    _: User = Depends(require_role(Role.ADMIN)),
    __: None = Depends(require_idempotency),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    sched = ReportSchedule(
        name=body.name, report_type=body.report_type, cron=body.cron,
        group_ids=body.group_ids, enabled=body.enabled,
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    await reload_report_jobs()
    return ok(_schedule_dump(sched, report_next_runs()))


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    body: ReportScheduleUpdate,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    sched = await db.get(ReportSchedule, schedule_id)
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报表计划不存在")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(sched, key, value)
    await db.commit()
    await db.refresh(sched)
    await reload_report_jobs()
    return ok(_schedule_dump(sched, report_next_runs()))


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    sched = await db.get(ReportSchedule, schedule_id)
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报表计划不存在")
    await db.delete(sched)
    await db.commit()
    await reload_report_jobs()
    return ok({"deleted": schedule_id})


@router.post("/schedules/{schedule_id}/run-now")
async def run_schedule_now(
    schedule_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    __: None = Depends(require_idempotency),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    sched = await db.get(ReportSchedule, schedule_id)
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报表计划不存在")
    try:
        summary = await run_report_schedule(schedule_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ok(summary)
