"""通知配置 API（A7）：渠道 / 接收人 / 接收组 / 级别路由 / 连通测试 / 发送记录。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_idempotency, require_role
from app.core.db import get_db
from app.core.security import Role
from app.models.notify import (
    NotifyChannel,
    NotifyLog,
    NotifyRoute,
    Recipient,
    RecipientGroup,
    RecipientGroupMember,
)
from app.models.user import User
from app.notify.channels import ChannelError, get_adapter
from app.notify.config_crypto import (
    apply_config_update,
    decrypt_config,
    encrypt_config,
    mask_config,
)
from app.schemas.common import ok
from app.schemas.notify import (
    ChannelInput,
    ChannelOutput,
    ChannelUpdate,
    GroupInput,
    GroupOutput,
    NotifyLogOutput,
    RecipientInput,
    RecipientOutput,
    RecipientUpdate,
    RouteInput,
    RouteOutput,
    RouteUpdate,
    build_channel_config_out,
    has_contact,
)

router = APIRouter(prefix="/notify", tags=["通知配置"])


# ---------------- 渠道 ----------------
def _channel_dump(c: NotifyChannel) -> dict[str, object]:
    return ChannelOutput(
        id=c.id,
        type=c.type,
        name=c.name,
        config=build_channel_config_out(c.type, mask_config(c.config or {})),
        enabled=c.enabled,
    ).model_dump()


@router.get("/channels")
async def list_channels(
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rows = (await db.execute(select(NotifyChannel).order_by(NotifyChannel.id))).scalars().all()
    return ok([_channel_dump(c) for c in rows])


@router.post("/channels")
async def create_channel(
    body: ChannelInput,
    _: User = Depends(require_role(Role.ADMIN)),
    __: None = Depends(require_idempotency),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    channel = NotifyChannel(
        type=body.type,
        name=body.name,
        config=encrypt_config(body.config_for_storage()),
        enabled=body.enabled,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return ok(_channel_dump(channel))


@router.put("/channels/{channel_id}")
async def update_channel(
    channel_id: int,
    body: ChannelUpdate,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    channel = await db.get(NotifyChannel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "渠道不存在")
    if body.name is not None:
        channel.name = body.name
    if body.enabled is not None:
        channel.enabled = body.enabled
    if body.config is not None:
        channel.config = apply_config_update(channel.config or {}, body.config)
    await db.commit()
    await db.refresh(channel)
    return ok(_channel_dump(channel))


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    channel = await db.get(NotifyChannel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "渠道不存在")
    await db.delete(channel)
    await db.commit()
    return ok({"deleted": channel_id})


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    channel = await db.get(NotifyChannel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "渠道不存在")
    adapter = get_adapter(channel.type)
    if adapter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的渠道类型 {channel.type}")
    try:
        await adapter.test(await decrypt_config(channel.config or {}))
    except ChannelError as exc:
        return ok({"ok": False, "detail": str(exc)})
    return ok({"ok": True, "detail": "连通正常"})


# ---------------- 接收人 ----------------
@router.get("/recipients")
async def list_recipients(
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rows = (await db.execute(select(Recipient).order_by(Recipient.id))).scalars().all()
    return ok([RecipientOutput.model_validate(r, from_attributes=True).model_dump() for r in rows])


@router.post("/recipients")
async def create_recipient(
    body: RecipientInput,
    _: User = Depends(require_role(Role.ADMIN)),
    __: None = Depends(require_idempotency),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    r = Recipient(**body.model_dump())
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return ok(RecipientOutput.model_validate(r, from_attributes=True).model_dump())


@router.put("/recipients/{recipient_id}")
async def update_recipient(
    recipient_id: int,
    body: RecipientUpdate,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    r = await db.get(Recipient, recipient_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接收人不存在")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(r, key, value)
    # 审查 M3：部分更新可能清空唯一联系方式，使接收人不可触达且通知时被静默跳过。
    # 合并后复验至少保留一种联系方式（与创建口径一致）。
    if not has_contact(r.phone, r.email, r.dingtalk_id, r.wecom_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "接收人至少需要一种联系方式（phone/email/dingtalk_id/wecom_id）",
        )
    await db.commit()
    await db.refresh(r)
    return ok(RecipientOutput.model_validate(r, from_attributes=True).model_dump())


@router.delete("/recipients/{recipient_id}")
async def delete_recipient(
    recipient_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    r = await db.get(Recipient, recipient_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接收人不存在")
    await db.delete(r)
    await db.commit()
    return ok({"deleted": recipient_id})


# ---------------- 接收组 ----------------
async def _group_members(db: AsyncSession, group_id: int) -> list[int]:
    rows = (
        await db.execute(
            select(RecipientGroupMember.recipient_id).where(
                RecipientGroupMember.group_id == group_id
            )
        )
    ).scalars().all()
    return list(rows)


async def _set_members(db: AsyncSession, group_id: int, member_ids: list[int]) -> None:
    await db.execute(
        delete(RecipientGroupMember).where(RecipientGroupMember.group_id == group_id)
    )
    for rid in set(member_ids):
        db.add(RecipientGroupMember(group_id=group_id, recipient_id=rid))


@router.get("/groups")
async def list_groups(
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    groups = (await db.execute(select(RecipientGroup).order_by(RecipientGroup.id))).scalars().all()
    out = []
    for g in groups:
        members = await _group_members(db, g.id)
        out.append(GroupOutput(id=g.id, name=g.name, member_ids=members).model_dump())
    return ok(out)


@router.post("/groups")
async def create_group(
    body: GroupInput,
    _: User = Depends(require_role(Role.ADMIN)),
    __: None = Depends(require_idempotency),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    g = RecipientGroup(name=body.name)
    db.add(g)
    await db.flush()
    await _set_members(db, g.id, body.member_ids)
    await db.commit()
    members = sorted(set(body.member_ids))
    return ok(GroupOutput(id=g.id, name=g.name, member_ids=members).model_dump())


@router.put("/groups/{group_id}")
async def update_group(
    group_id: int,
    body: GroupInput,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    g = await db.get(RecipientGroup, group_id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接收组不存在")
    g.name = body.name
    await _set_members(db, group_id, body.member_ids)
    await db.commit()
    members = sorted(set(body.member_ids))
    return ok(GroupOutput(id=group_id, name=g.name, member_ids=members).model_dump())


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    g = await db.get(RecipientGroup, group_id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接收组不存在")
    await db.delete(g)
    await db.commit()
    return ok({"deleted": group_id})


# ---------------- 级别路由 ----------------
def _route_dump(r: NotifyRoute) -> dict[str, object]:
    return RouteOutput.model_validate(r, from_attributes=True).model_dump()


@router.get("/routes")
async def list_routes(
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rows = (await db.execute(select(NotifyRoute).order_by(NotifyRoute.level))).scalars().all()
    return ok([_route_dump(r) for r in rows])


@router.post("/routes")
async def create_route(
    body: RouteInput,
    _: User = Depends(require_role(Role.ADMIN)),
    __: None = Depends(require_idempotency),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    route = NotifyRoute(**body.model_dump())
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return ok(_route_dump(route))


@router.put("/routes/{route_id}")
async def update_route(
    route_id: int,
    body: RouteUpdate,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    route = await db.get(NotifyRoute, route_id)
    if route is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "路由不存在")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(route, key, value)
    await db.commit()
    await db.refresh(route)
    return ok(_route_dump(route))


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    route = await db.get(NotifyRoute, route_id)
    if route is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "路由不存在")
    await db.delete(route)
    await db.commit()
    return ok({"deleted": route_id})


# ---------------- 发送记录 ----------------
@router.get("/logs")
async def list_logs(
    alarm_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    stmt = select(NotifyLog)
    if alarm_id is not None:
        stmt = stmt.where(NotifyLog.alarm_id == alarm_id)
    stmt = stmt.order_by(NotifyLog.sent_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return ok([
        NotifyLogOutput.model_validate(r, from_attributes=True).model_dump(mode="json")
        for r in rows
    ])
