"""
模拟共济 EMS 北向接口服务 (Mock 共济 EMS)
=========================================
用途：在没有真实共济 EMS 的情况下，为「动环监控预警平台」提供可联调的南向数据源。
严格遵循《共济基础设施监控数据接入标准 V2.23》的报文格式。

实现接口：
  客户端被调：/north/login /heart /logout
             /get_space_list /get_device_list /get_spot_list
             /online_data_subscribe /online_data /offline_value
             /online_alarm_subscribe /offline_alarm /get_event_rules
  主动推送（向平台 recv 地址 POST）：
             /north/online_data_push   每 10s 周期全量
             /north/online_alarm_push  注入设备级事件(通信中断/故障/停采)

运行：
  pip install -r requirements.txt
  uvicorn mock_ems_server:app --host 0.0.0.0 --port 9000

平台侧把 EMS 连接配置为  http://<mock_host>:9000 ，并在 login 请求里声明平台自身
接收推送的 ip/port；订阅后本 mock 会持续向该地址推送数据。
"""
import asyncio
import random
import time
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, Header, Request

app = FastAPI(title="Mock 共济 EMS", version="V2.23-mock")

VERSION = "20170714124155"

# ----------------------------------------------------------------------------
# 内存状态
# ----------------------------------------------------------------------------
STATE = {
    "token": None,
    "recv_ip": None,      # 平台接收推送 ip（login 时上报）
    "recv_port": None,    # 平台接收推送 port
    "data_subscribed": False,
    "alarm_subscribed": False,
    "last_heart": 0.0,
}

# ----------------------------------------------------------------------------
# 样例拓扑：1 区域 → 1 房间 → 4 设备 → 若干测点
# point 生成器：base 基准, amp 波动幅度, noise 噪声, hi 触发"过高"的注入阈值
# ----------------------------------------------------------------------------
SPACES = [
    {"resource_id": "0_root", "name": "厦门数据中心", "ci_type": "5",
     "location": "project_root/", "parent_id": "", "space_type": "1"},
    {"resource_id": "0_room1", "name": "核心机房", "ci_type": "5",
     "location": "project_root/0_root", "parent_id": "0_root", "space_type": "5"},
]

DEVICES = [
    {"resource_id": "d_ups1",   "name": "1#UPS",       "device_type": "UPS设备",
     "parent_id": "0_room1", "location": "project_root/0_root/0_room1", "link": ""},
    {"resource_id": "d_crac1",  "name": "1#精密空调",   "device_type": "精密空调",
     "parent_id": "0_room1", "location": "project_root/0_root/0_room1", "link": ""},
    {"resource_id": "d_th1",    "name": "1#温湿度",     "device_type": "TH03温湿度",
     "parent_id": "0_room1", "location": "project_root/0_root/0_room1", "link": ""},
    {"resource_id": "d_pdu1",   "name": "1#列头柜",     "device_type": "配电",
     "parent_id": "0_room1", "location": "project_root/0_root/0_room1", "link": ""},
]

# 每个测点：id, name, spot_type(1模拟2状态), unit, 生成参数
POINTS = {
    "d_ups1": [
        {"id": "d_ups1_p_outv", "name": "UPS输出电压", "spot_type": "1", "unit": "V",
         "gen": {"base": 220, "amp": 3, "noise": 1, "hi": 245}},
        {"id": "d_ups1_p_load", "name": "UPS负载率", "spot_type": "1", "unit": "%",
         "gen": {"base": 55, "amp": 8, "noise": 2, "hi": 90}},
        {"id": "d_ups1_p_batt", "name": "电池电压", "spot_type": "1", "unit": "V",
         "gen": {"base": 240, "amp": 2, "noise": 1, "hi": 999}},
    ],
    "d_crac1": [
        {"id": "d_crac1_p_st", "name": "空调运行状态", "spot_type": "2", "unit": "",
         "mapper": "1=运行;0=停机", "gen": {"base": 1, "amp": 0, "noise": 0, "hi": 999}},
        {"id": "d_crac1_p_supt", "name": "送风温度", "spot_type": "1", "unit": "℃",
         "gen": {"base": 18, "amp": 2, "noise": 0.5, "hi": 28}},
    ],
    "d_th1": [
        {"id": "d_th1_p_temp", "name": "机房温度", "spot_type": "1", "unit": "℃",
         "gen": {"base": 24, "amp": 2.5, "noise": 0.6, "hi": 32}},
        {"id": "d_th1_p_humi", "name": "机房湿度", "spot_type": "1", "unit": "%RH",
         "gen": {"base": 50, "amp": 8, "noise": 2, "hi": 75}},
    ],
    "d_pdu1": [
        {"id": "d_pdu1_p_cur", "name": "总电流", "spot_type": "1", "unit": "A",
         "gen": {"base": 120, "amp": 15, "noise": 5, "hi": 200}},
        {"id": "d_pdu1_p_pow", "name": "总功率", "spot_type": "1", "unit": "kW",
         "gen": {"base": 45, "amp": 6, "noise": 2, "hi": 80}},
    ],
}

# 注入控制：每隔若干轮，对某测点注入一次超限值，触发平台规则引擎
_inject_counter = {"n": 0}


def _gen_value(p) -> float:
    g = p["gen"]
    if p["spot_type"] == "2":          # 状态量
        return float(g["base"])
    v = g["base"] + random.uniform(-g["amp"], g["amp"]) + random.uniform(-g["noise"], g["noise"])
    return round(v, 2)


def _maybe_inject(p, value: float) -> float:
    """周期性把某个模拟量顶到超限，便于验证平台告警。"""
    if p["spot_type"] != "1":
        return value
    _inject_counter["n"] += 1
    # 约每 80 个点值注入一次超限（一轮全量约 9 个模拟量，故 ~每 9 轮一次）
    if random.random() < 0.012:
        return round(p["gen"]["hi"] + random.uniform(1, 5), 2)
    return value


# ----------------------------------------------------------------------------
# 响应包装
# ----------------------------------------------------------------------------
def ok(data):
    return {"error_code": 0, "error_msg": "ok", "data": data}


def err(code: int, msg: str):
    return {"error_code": code, "error_msg": msg, "data": {}}


async def _read_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body.get("data", {}) if isinstance(body, dict) else {}


def _check_token(token: Optional[str]) -> bool:
    return STATE["token"] is not None and token == STATE["token"]


# ----------------------------------------------------------------------------
# 客户端被调接口
# ----------------------------------------------------------------------------
@app.post("/north/login")
async def login(request: Request):
    data = await _read_body(request)
    username = data.get("username")
    password = data.get("password")
    # mock 固定校验：admin / 123456（可按需放宽）
    if username != "admin" or password != "123456":
        return err(100, "user name or password is wrong")
    STATE["token"] = uuid.uuid4().hex
    STATE["recv_ip"] = data.get("ip")
    STATE["recv_port"] = data.get("port") or "80"
    STATE["last_heart"] = time.time()
    print(f"[login] token={STATE['token'][:8]}.. recv={STATE['recv_ip']}:{STATE['recv_port']}")
    return ok({"token": STATE["token"]})


@app.post("/north/heart")
async def heart(token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    STATE["last_heart"] = time.time()
    return ok({})


@app.post("/north/logout")
async def logout(token: Optional[str] = Header(default=None)):
    STATE.update({"token": None, "data_subscribed": False, "alarm_subscribed": False})
    print("[logout]")
    return ok({})


@app.post("/north/get_space_list")
async def get_space_list(token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    return ok({"total_count": len(SPACES), "resource_count": len(SPACES), "resources": SPACES})


@app.post("/north/get_device_list")
async def get_device_list(token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    res = [{**d, "ci_type": "2"} for d in DEVICES]
    return ok({"total_count": len(res), "resource_count": len(res), "resources": res})


@app.post("/north/get_spot_list")
async def get_spot_list(request: Request, token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    data = await _read_body(request)
    ids = data.get("resource_ids", []) or [d["resource_id"] for d in DEVICES]
    devices = []
    for dev_id in ids:
        pts = []
        for p in POINTS.get(dev_id, []):
            pts.append({
                "resource_id": p["id"], "name": p["name"], "ci_type": "3",
                "spot_type": p["spot_type"], "unit": p.get("unit", ""),
                "mapper": p.get("mapper", ""), "parent_id": dev_id, "access": "r",
                "event_rules": [_rule_str(p)],
                "filter": "filter=DefFilter;max=10000;min=-10000;times=2",
            })
        devices.append({"resource_id": dev_id, "points": pts})
    return ok({"resource_count": len(devices), "devices": devices})


def _rule_str(p) -> str:
    hi = p["gen"]["hi"]
    return (f"id=1;event_generator=DefEventGenerator;operator=>;operand={hi};"
            f"restore_operator=<;restore_operand={hi-5};content={p['name']}过高;"
            f"suggest=;alarm_type=2;level=2;disabled=false;codec=;codecex=;"
            f"twinkle_time=0;continuous_time=0")


@app.post("/north/online_data_subscribe")
async def online_data_subscribe(request: Request, token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    data = await _read_body(request)
    STATE["data_subscribed"] = bool(data.get("subscribe", True))
    print(f"[online_data_subscribe] {STATE['data_subscribed']}")
    return ok({})


@app.post("/north/online_alarm_subscribe")
async def online_alarm_subscribe(request: Request, token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    data = await _read_body(request)
    STATE["alarm_subscribed"] = bool(data.get("subscribe", True))
    print(f"[online_alarm_subscribe] {STATE['alarm_subscribed']}")
    return ok({})


@app.post("/north/online_data")
async def online_data(request: Request, token: Optional[str] = Header(default=None)):
    """在线拉取：device_ids 与 spot_ids 互斥。"""
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    data = await _read_body(request)
    device_ids = data.get("device_ids") or []
    spot_ids = data.get("spot_ids") or []
    now = int(time.time())
    points = []
    if spot_ids:
        flat = {p["id"]: p for ps in POINTS.values() for p in ps}
        for sid in spot_ids:
            if sid in flat:
                points.append({"resource_id": sid, "real_value": str(_gen_value(flat[sid])),
                               "save_time": now})
    else:
        targets = device_ids or [d["resource_id"] for d in DEVICES]
        for dev_id in targets:
            for p in POINTS.get(dev_id, []):
                points.append({"resource_id": p["id"], "real_value": str(_gen_value(p)),
                               "save_time": now})
    return ok({"points": points})


@app.post("/north/offline_value")
async def offline_value(request: Request, token: Optional[str] = Header(default=None)):
    """历史数据：遵守 ≤100 测点、≤1 天限制（mock 仅做软校验提示）。"""
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    data = await _read_body(request)
    start = int(data.get("start", 0))
    end = int(data.get("end", 0))
    ids = data.get("resource_ids", [])
    interval = data.get("interval", "five")
    if len(ids) > 100:
        return err(1, "abnormal parameter: too many resource_ids (>100)")
    if end - start > 86400:
        return err(1, "abnormal parameter: time span > 1 day")
    step = {"five": 300, "ten": 600, "quarter": 900, "twenty": 1200,
            "half": 1800, "hour": 3600}.get(interval, 300)
    flat = {p["id"]: p for ps in POINTS.values() for p in ps}
    result = []
    for rid in ids:
        p = flat.get(rid)
        dl = []
        t = start
        while t <= end and p is not None:
            dl.append({"value": str(_gen_value(p)), "time": str(t)})
            t += step
        result.append({"resource_id": rid, "data_list": dl})
    return ok(result)


@app.post("/north/offline_alarm")
async def offline_alarm(request: Request, token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    data = await _read_body(request)
    begin = int(data.get("begin_time", int(time.time()) - 3600))
    # mock 返回 1 条样例历史告警
    sample = {
        "guid": str(uuid.uuid4()), "resource_id": "d_th1_p_temp",
        "event_location": "project_root/0_root/0_room1", "event_source": "核心机房/1#温湿度",
        "masked": 0, "event_snapshot": "33.5", "event_level": "2", "event_time": begin,
        "content": "机房温度过高", "recover_time": begin + 300, "recover_des": "",
        "recover_by": "", "confirm_time": 0, "confirm_des": "", "confirm_by": "",
        "cep_processed": 0, "accept_time": 0, "accept_des": "", "accept_by": "",
        "event_suggest": "检查空调制冷",
    }
    return ok({"total": 1, "alarm": [sample]})


@app.post("/north/get_event_rules")
async def get_event_rules(request: Request, token: Optional[str] = Header(default=None)):
    if not _check_token(token):
        return err(2, "abnormal TOKEN")
    data = await _read_body(request)
    ids = data.get("resource_ids", [])
    flat = {p["id"]: p for ps in POINTS.values() for p in ps}
    out = []
    for rid in ids:
        p = flat.get(rid)
        if not p:
            continue
        hi = p["gen"]["hi"]
        out.append({"resource_id": rid, "event_rules": [{
            "event_generator": "DefEventGenerator", "operator": ">", "operand": str(hi),
            "restore_operator": "<", "restore_operand": str(hi - 5), "alarm_type": "2",
            "level": "2", "twinkle_time": "", "continuous_time": "", "content": "",
            "suggest": "", "disabled": "false", "id": str(int(time.time()))}]})
    return ok(out)


# ----------------------------------------------------------------------------
# 主动推送任务
# ----------------------------------------------------------------------------
def _platform_url(path: str) -> Optional[str]:
    if not STATE["recv_ip"]:
        return None
    return f"http://{STATE['recv_ip']}:{STATE['recv_port']}{path}"


async def _push_loop():
    """每 10s 向平台推送一轮全量实时数据（订阅开启且已登录时）。"""
    while True:
        await asyncio.sleep(10)
        if not (STATE["token"] and STATE["data_subscribed"]):
            continue
        url = _platform_url("/north/online_data_push")
        if not url:
            continue
        now = int(time.time())
        devices = []
        for d in DEVICES:
            pts = []
            for p in POINTS.get(d["resource_id"], []):
                val = _maybe_inject(p, _gen_value(p))
                pts.append({"resource_id": p["id"], "real_value": str(val), "save_time": now})
            devices.append({"resource_id": d["resource_id"], "status": 1, "points": pts})
        payload = {"version": VERSION, "data": {
            "period": now, "page_no": 1, "page_size": len(devices), "devices": devices}}
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(url, json=payload)
        except Exception as e:
            print(f"[push_data] 推送失败(平台未就绪?): {e}")


async def _alarm_loop():
    """周期性注入设备级 EMS 事件（通信中断/故障/停采），验证平台 EMS 告警接入。"""
    device_events = [(0, "通信中断"), (21, "设备故障"), (30, "停止采集")]
    while True:
        await asyncio.sleep(60)
        if not (STATE["token"] and STATE["alarm_subscribed"]):
            continue
        url = _platform_url("/north/online_alarm_push")
        if not url:
            continue
        if random.random() > 0.5:    # 约每 2 分钟一次
            continue
        et, name = random.choice(device_events)
        dev = random.choice(DEVICES)
        now = int(time.time())
        alarm = {
            "guid": f"{uuid.uuid4()}__{et}", "resource_id": dev["resource_id"],
            "event_location": dev["location"], "event_source": f"核心机房/{dev['name']}",
            "msg_type": 0, "masked": 0,
            "event_alarm": {"event_type": et, "event_snapshot": "",
                            "event_level": "2", "event_time": now,
                            "content": f"{dev['name']}{name}", "event_suggest": ""},
            "event_recover": {"recover_time": 0, "recover_des": "", "recover_by": ""},
            "event_accept": {"accept_time": 0, "accept_des": "", "accept_by": ""},
            "event_confirm": {"confirm_time": 0, "confirm_des": "", "confirm_by": ""},
        }
        payload = {"version": VERSION, "data": {"alarms": [alarm]}}
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(url, json=payload)
            print(f"[push_alarm] {dev['name']} {name}(event_type={et})")
        except Exception as e:
            print(f"[push_alarm] 推送失败: {e}")


@app.on_event("startup")
async def _startup():
    asyncio.create_task(_push_loop())
    asyncio.create_task(_alarm_loop())
    print("Mock 共济 EMS 已启动 :9000  （登录账号 admin/123456）")


@app.get("/")
async def root():
    return {"service": "Mock 共济 EMS", "standard": "V2.23",
            "login": "admin/123456", "state": {k: v for k, v in STATE.items() if k != "token"}}
