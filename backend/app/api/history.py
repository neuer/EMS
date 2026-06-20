"""历史数据路由：趋势查询（分层选层）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.history.query import query_history
from app.models.user import User
from app.schemas.common import ok
from app.schemas.history import HistoryQuery

router = APIRouter(prefix="/history", tags=["历史数据"])


@router.post("/query")
async def history_query(
    body: HistoryQuery,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """历史趋势查询；body：{point_ids[], start, end, agg}。

    查询走本地 DB（原始层/5min 降采样层），不触达 EMS。
    """
    result = await query_history(db, body.point_ids, body.start, body.end, body.agg)
    return ok(result.model_dump())
