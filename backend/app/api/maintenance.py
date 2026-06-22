"""维护窗口 API（A6）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_idempotency, require_role
from app.core.db import get_db
from app.core.security import Role
from app.models.suppress import MaintenanceWindow
from app.models.user import User
from app.schemas.common import ok
from app.schemas.suppress import MaintenanceInput, MaintenanceOutput, MaintenanceUpdate

router = APIRouter(prefix="/maintenance", tags=["抑制-维护窗口"])


def _dump(w: MaintenanceWindow) -> dict[str, object]:
    return MaintenanceOutput.model_validate(w, from_attributes=True).model_dump(mode="json")


@router.get("")
async def list_windows(
    _: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rows = (
        await db.execute(select(MaintenanceWindow).order_by(MaintenanceWindow.start_at.desc()))
    ).scalars().all()
    return ok([_dump(w) for w in rows])


@router.post("")
async def create_window(
    body: MaintenanceInput,
    current: User = Depends(require_role(Role.OPERATOR)),
    __: None = Depends(require_idempotency),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    win = MaintenanceWindow(**body.model_dump(), created_by=current.id)
    db.add(win)
    await db.commit()
    await db.refresh(win)
    return ok(_dump(win))


@router.put("/{window_id}")
async def update_window(
    window_id: int,
    body: MaintenanceUpdate,
    _: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    win = await db.get(MaintenanceWindow, window_id)
    if win is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "维护窗口不存在")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(win, key, value)
    await db.commit()
    await db.refresh(win)
    return ok(_dump(win))


@router.delete("/{window_id}")
async def delete_window(
    window_id: int,
    _: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    win = await db.get(MaintenanceWindow, window_id)
    if win is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "维护窗口不存在")
    await db.delete(win)
    await db.commit()
    return ok({"deleted": window_id})
