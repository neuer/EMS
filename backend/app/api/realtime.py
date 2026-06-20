"""实时数据路由：批量取测点最新值（走 Redis）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.constants import REDIS_POINT_LATEST
from app.core.redis import redis_client
from app.models.user import User
from app.schemas.common import ok
from app.schemas.realtime import PointLatest

router = APIRouter(prefix="/realtime", tags=["实时数据"])


@router.get("/points")
async def get_points_latest(
    ids: str = Query(..., description="逗号分隔的测点 id"),
    _: User = Depends(get_current_user),
) -> dict[str, object]:
    point_ids = [p.strip() for p in ids.split(",") if p.strip()]
    pipe = redis_client.pipeline()
    for pid in point_ids:
        pipe.hgetall(REDIS_POINT_LATEST.format(point_id=pid))
    rows = await pipe.execute()

    out: list[dict[str, object]] = []
    for pid, h in zip(point_ids, rows, strict=True):
        save_time = h.get("save_time") if h else None
        out.append(
            PointLatest(
                id=pid,
                value=h.get("value") if h else None,
                save_time=int(save_time) if save_time not in (None, "") else None,
            ).model_dump()
        )
    return ok(out)
