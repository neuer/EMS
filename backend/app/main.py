"""FastAPI 入口：装配全部业务路由、EMS 连接管理、调度器与通知 worker。

- 基建：core、健康检查（/health 含 db/redis/ems/failures）、认证、默认管理员 seed。
- 采集：EMS 连接管理（登录/心跳/重连/订阅）、配置同步、实时落库、/north 推送接收端点。
- 业务：实时/历史、规则引擎与告警中心、抑制/维护窗口、通知派发、报表。
- 后台：APScheduler（定时同步/回补巡检/摘要/定时报表）、通知事件 worker。
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    alarms,
    assets,
    auth,
    health,
    history,
    maintenance,
    mute,
    realtime,
    reports,
    rules,
    sync,
    users,
    ws,
)
from app.api import (
    notify as notify_api,
)
from app.api import (
    settings as settings_api,
)
from app.core.config import settings
from app.core.context import set_request_id
from app.core.logging import get_logger, setup_logging
from app.ems import push_server
from app.ems.connection import start_connection_manager, stop_connection_manager
from app.notify.dispatcher import start_notify_worker, stop_notify_worker
from app.scheduler import start_scheduler, stop_scheduler
from app.schemas.common import fail
from app.seed import seed_default_admin, seed_ems_config

logger = get_logger("app")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    logger.info("应用启动", extra={"extra_fields": {"env": settings.environment}})
    # 初始化默认数据（幂等）
    try:
        await seed_default_admin()
        await seed_ems_config()
    except Exception as exc:
        logger.error("初始化 seed 失败", extra={"extra_fields": {"error": str(exc)}})

    # 启动通知 worker（订阅告警事件总线；与 EMS 连接无关，始终启动）
    try:
        await start_notify_worker()
    except Exception as exc:
        logger.error("启动通知 worker 失败", extra={"extra_fields": {"error": str(exc)}})

    # 启动 EMS 连接管理与调度器
    if settings.ems_auto_connect:
        try:
            await start_connection_manager()
            await start_scheduler()
        except Exception as exc:
            logger.error("启动连接管理失败", extra={"extra_fields": {"error": str(exc)}})

    yield

    # 优雅关闭
    stop_scheduler()
    await stop_connection_manager()
    await stop_notify_worker()
    logger.info("应用关闭")


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # 审查 C1：收敛为内网来源，不再通配
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

REQUEST_ID_HEADER = "X-Request-ID"


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):  # noqa: ANN001, ANN201
    """红线 §10：为每个请求生成/透传 request_id，写入上下文与响应头，贯穿日志链路。"""
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    set_request_id(request_id)
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """统一错误模型（红线 §16）：HTTPException → {code,msg,data}，code 取 HTTP 状态码。"""
    return JSONResponse(status_code=exc.status_code, content=fail(exc.status_code, str(exc.detail)))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求校验失败：422 + 结构化字段错误（details，§16.1）。"""
    return JSONResponse(
        status_code=422,
        content=fail(422, "请求参数校验失败", jsonable_encoder(exc.errors())),
    )

# 健康检查与 EMS 推送接收端点挂根路径（推送目标为 recv_ip:recv_port/north/...）
app.include_router(health.router)
app.include_router(push_server.router)
# WebSocket 网关挂根路径（/ws/realtime，由 nginx 反代 /ws/）
app.include_router(ws.router)

# 平台业务 API 统一前缀 /api/v1
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(settings_api.router, prefix=API_PREFIX)
app.include_router(sync.router, prefix=API_PREFIX)
app.include_router(assets.router, prefix=API_PREFIX)
app.include_router(realtime.router, prefix=API_PREFIX)
app.include_router(history.router, prefix=API_PREFIX)
app.include_router(rules.router, prefix=API_PREFIX)
app.include_router(alarms.router, prefix=API_PREFIX)
app.include_router(mute.router, prefix=API_PREFIX)
app.include_router(maintenance.router, prefix=API_PREFIX)
app.include_router(notify_api.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "version": "0.2.0"}
