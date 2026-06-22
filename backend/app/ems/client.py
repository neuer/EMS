"""共济 EMS 客户端：封装北向调用，统一包头/token/error_code/超时。

红线：
- #1 纯只读：不封装 setting / set_event_rules。
- #3 报文格式：请求 {"version":...,"data":{...}}；除 login 外 Header 带 token。
- #20 外部 HTTP 必须配置连接/读取超时。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.ems.protocol import EmsError, EmsTransportError

logger = get_logger("ems")


class EmsClient:
    """单实例持有的 EMS HTTP 客户端。token 由连接管理写入。"""

    def __init__(self, base_url: str, version: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._version = version
        self.token: str | None = None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.ems_connect_timeout,
                read=settings.ems_read_timeout,
                write=settings.ems_read_timeout,
                pool=settings.ems_connect_timeout,
            ),
            # 审查 I11：限制连接池上限，避免 EMS 慢响应时连接无界堆积（心跳/回补/拉取共用本 client）
            # 耗尽本地句柄、互相饿死。pool timeout 仅控「等连接」，不限并发数，故显式设 limits。
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(
        self, path: str, data: dict[str, Any], *, with_token: bool = True
    ) -> dict[str, Any]:
        """统一 POST：包头封装、token 头、error_code 校验。"""
        body = {"version": self._version, "data": data}
        headers: dict[str, str] = {}
        if with_token:
            if not self.token:
                raise EmsTransportError("缺少 token，无法发起需鉴权的请求")
            headers["token"] = self.token
        url = f"{self._base_url}{path}"
        try:
            resp = await self._client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise EmsTransportError(f"HTTP 调用失败 {path}: {exc}") from exc

        code = payload.get("error_code")
        if code != 0:
            # 审查 B7：error_code 为畸形非整数时，int() 抛 ValueError 会逃逸 EmsError/
            # EmsTransportError 分类。归一为传输错误，使上层重连逻辑能正确兜住。
            try:
                code_int = int(code) if code is not None else -1
            except (TypeError, ValueError):
                raise EmsTransportError(f"非法 error_code: {code!r}") from None
            raise EmsError(code_int, payload.get("error_msg", ""))
        # 响应空值键必须保留，data 缺失时回退空 dict
        result = payload.get("data")
        return result if isinstance(result, dict) else {"_raw": result}

    # ---- 连接管理 ----
    async def login(self, username: str, password: str, recv_ip: str, recv_port: str) -> str:
        """登录：上报本平台接收推送 ip/port；成功后保存并返回 token。"""
        data = await self._post(
            "/north/login",
            {"username": username, "password": password, "ip": recv_ip, "port": recv_port},
            with_token=False,
        )
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise EmsTransportError("登录响应缺少 token")
        self.token = token
        return token

    async def heart(self) -> None:
        await self._post("/north/heart", {})

    async def logout(self) -> None:
        await self._post("/north/logout", {})
        self.token = None

    # ---- 配置同步 ----
    async def get_space_list(self) -> list[dict[str, Any]]:
        data = await self._post("/north/get_space_list", {})
        return list(data.get("resources") or [])

    async def get_device_list(self) -> list[dict[str, Any]]:
        data = await self._post("/north/get_device_list", {})
        return list(data.get("resources") or [])

    async def get_spot_list(self, resource_ids: list[str]) -> list[dict[str, Any]]:
        """按设备 id 批量取测点；返回 devices[]{resource_id, points[]}。"""
        data = await self._post("/north/get_spot_list", {"resource_ids": resource_ids})
        return list(data.get("devices") or [])

    # ---- 实时采集 ----
    async def online_data_subscribe(self, subscribe: bool = True) -> None:
        await self._post("/north/online_data_subscribe", {"subscribe": subscribe})

    async def online_alarm_subscribe(self, subscribe: bool = True) -> None:
        await self._post("/north/online_alarm_subscribe", {"subscribe": subscribe})

    async def online_data(
        self,
        device_ids: list[str] | None = None,
        spot_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """在线拉取（兜底）。device_ids 与 spot_ids 互斥。"""
        if device_ids and spot_ids:
            raise ValueError("device_ids 与 spot_ids 互斥，只能二选一")
        payload: dict[str, Any] = {}
        if spot_ids:
            payload["spot_ids"] = spot_ids
        else:
            payload["device_ids"] = device_ids or []
        data = await self._post("/north/online_data", payload)
        return list(data.get("points") or [])

    # ---- 历史数据（趋势 / 断连回补）----
    async def offline_value(
        self,
        start: int,
        end: int,
        resource_ids: list[str],
        interval: str = "five",
    ) -> list[dict[str, Any]]:
        """历史数据查询。

        红线 #5：调用方须保证 resource_ids ≤100、跨度 ≤1 天、串行（锁）；本方法只做单次调用。
        interval ∈ {five,ten,quarter,twenty,half,hour}。
        返回 [{resource_id, data_list:[{value,time}]}]。
        EMS 该接口 data 为 list，_post 会包成 {"_raw": [...]}，此处解包。
        """
        data = await self._post(
            "/north/offline_value",
            {"start": start, "end": end, "resource_ids": resource_ids, "interval": interval},
        )
        raw = data.get("_raw") if "_raw" in data else data
        if isinstance(raw, list):
            return list(raw)
        # 审查 H5：error_code=0 但 data 结构不符契约（非 list）→ 记 warning 而非静默返回空，
        # 否则调用方会把「响应畸形」误判为「该窗口无数据」。
        logger.warning(
            "offline_value 返回结构非预期（非 list），按空结果处理",
            extra={"extra_fields": {"type": type(raw).__name__, "points": len(resource_ids)}},
        )
        return []
