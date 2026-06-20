"""测点屏蔽 API（A6）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.db import get_db
from app.core.security import Role
from app.models.suppress import PointMute
from app.models.user import User
from app.schemas.common import ok
from app.schemas.suppress import MuteInput, MuteOutput

router = APIRouter(prefix="/mute", tags=["抑制-屏蔽"])


def _dump(m: PointMute) -> dict[str, object]:
    return MuteOutput.model_validate(m, from_attributes=True).model_dump(mode="json")


@router.get("")
async def list_mute(
    point_id: str | None = Query(None),
    _: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    stmt = select(PointMute).where(PointMute.enabled.is_(True))
    if point_id:
        stmt = stmt.where(PointMute.point_id == point_id)
    rows = (await db.execute(stmt.order_by(PointMute.id.desc()))).scalars().all()
    return ok([_dump(m) for m in rows])


@router.post("")
async def create_mute(
    body: MuteInput,
    current: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = body.model_dump(exclude_none=True)
    mute = PointMute(**data, created_by=current.id)
    db.add(mute)
    await db.commit()
    await db.refresh(mute)
    return ok(_dump(mute))


@router.delete("/{mute_id}")
async def delete_mute(
    mute_id: int,
    _: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    mute = await db.get(PointMute, mute_id)
    if mute is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "屏蔽记录不存在")
    # 软关闭，保留历史
    mute.enabled = False
    await db.commit()
    return ok({"disabled": mute_id})
