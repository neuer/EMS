# API 规格

分两部分：**A. 平台自身 API**（前端 ↔ 后端）；**B. 共济 EMS 北向对接**（后端 ↔ EMS，遵循《标准 V2.23》）。

约定：平台自身 API 统一前缀 `/api/v1`，JSON，鉴权用 Bearer Token（登录态）。响应统一 `{"code":0,"msg":"ok","data":...}`。

---

## A. 平台自身 API

### A1. 认证与用户
| 方法 | 路径 | 说明 | 角色 |
|---|---|---|---|
| POST | `/auth/login` | 用户名密码登录，返回 token | 全部 |
| POST | `/auth/logout` | 登出 | 全部 |
| GET | `/auth/me` | 当前用户信息 | 全部 |
| GET/POST/PUT/DELETE | `/users` | 用户增删改查 | admin |

### A2. 资产树与元数据
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/tree/spaces` | 空间树（含子节点告警状态汇总） |
| GET | `/spaces/{id}/children` | 某空间下子空间/设备 |
| GET | `/devices` | 设备列表（筛选：space/group/tag/keyword） |
| GET | `/devices/{id}` | 设备详情（含测点列表、通信状态） |
| GET | `/points` | 测点列表（筛选：device/space/group/tag/keyword/importance） |
| GET | `/points/{id}` | 测点详情（当前值、单位、规则、元数据） |
| GET/PUT | `/assets/{id}/meta` | 读取/更新元数据增强（别名/分组/标签/重要度/单位/备注） |
| POST | `/sync/config` | 触发「立即同步」配置树 | admin |
| GET | `/sync/log` | 同步日志 |

### A3. 实时与历史数据
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/realtime/points?ids=...` | 批量取测点最新值（走 Redis） |
| WS | `/ws/realtime` | WebSocket：订阅测点集，服务端实时推送最新值 |
| POST | `/history/query` | 历史趋势查询；body：`{point_ids[], start, end, agg}`；agg=raw\|5min\|auto，auto 按范围自动选层 |
| GET | `/history/export` | 历史数据导出 CSV/Excel；参数同上 + format |
| POST | `/realtime/pull` | 触发主动拉取（兜底）；body：`{device_ids[]\|spot_ids[]}` |

**WS `/ws/realtime` 协议**
```
// 客户端→服务端 订阅
{ "action": "subscribe", "point_ids": ["0_101_1_1_0", "0_101_1_2_0"] }
// 服务端→客户端 实时帧
{ "type": "realtime", "points": [ {"id":"0_101_1_1_0","value":222.2,"ts":1468471315} ] }
// 服务端→客户端 告警事件(可选复用同通道)
{ "type": "alarm", "alarm": { ... } }
```

### A4. 预警规则
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/rules?point_id=` | 查询测点规则（含多档） |
| POST | `/rules` | 新增规则 | admin |
| PUT | `/rules/{id}` | 修改规则 | admin |
| DELETE | `/rules/{id}` | 删除规则 | admin |
| POST | `/rules/import-from-ems` | 从 EMS `get_event_rules` 导入为初值（可选） | admin |

### A5. 告警中心
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/alarms/active` | 活动告警列表（筛选：level/type/device/space/masked） |
| POST | `/alarms/history` | 历史告警查询；body：时间范围 + 多条件筛选 |
| GET | `/alarms/{id}` | 告警详情 + 生命周期事件流 |
| POST | `/alarms/{id}/accept` | 受理（备注） | operator+ |
| POST | `/alarms/{id}/confirm` | 确认（备注） | operator+ |
| POST | `/alarms/{id}/note` | 追加备注 | operator+ |
| GET | `/alarms/stats` | 告警统计（按级别/设备/时间，供大盘与报表） |

### A6. 抑制
| 方法 | 路径 | 说明 | 角色 |
|---|---|---|---|
| GET/POST/DELETE | `/mute` | 测点屏蔽增删查 | operator+ |
| GET/POST/PUT/DELETE | `/maintenance` | 维护窗口管理 | operator+ |

### A7. 通知配置
| 方法 | 路径 | 说明 | 角色 |
|---|---|---|---|
| GET/POST/PUT/DELETE | `/notify/channels` | 渠道管理（sms/email/dingtalk/wecom/voice/webhook） | admin |
| POST | `/notify/channels/{id}/test` | 渠道连通测试 | admin |
| GET/POST/PUT/DELETE | `/notify/recipients` | 接收人管理 | admin |
| GET/POST/PUT/DELETE | `/notify/groups` | 接收组管理 | admin |
| GET/POST/PUT/DELETE | `/notify/routes` | 按级别路由管理 | admin |
| GET | `/notify/logs` | 发送记录 | operator+ |

### A8. 报表与系统设置
| 方法 | 路径 | 说明 | 角色 |
|---|---|---|---|
| GET | `/reports/alarm?period=daily\|weekly\|monthly` | 即时生成告警统计报表 | operator+ |
| GET/POST/PUT/DELETE | `/reports/schedules` | 定时邮件报表计划 | admin |
| GET/PUT | `/settings/ems` | EMS 连接配置（密码写时加密，读时脱敏） | admin |
| GET | `/settings/ems/status` | EMS 连接状态（在线/心跳/推送/重连次数） | operator+ |
| GET/PUT | `/settings/storage` | 死区存储开关与阈值 | admin |
| GET | `/health` | 健康检查（DB/Redis/EMS 连接） | 公开内网 |

---

## B. 共济 EMS 北向对接映射

> 所有请求体含包头 `{"version": "<version_str>", "data": {...}}`；除 login 外 Header 携带 `token`。响应体 `{"error_code":0,"error_msg":"ok","data":{...}}`。下表「触发模块」对应 `04_架构` 中的后端模块。

### B1. 平台作为客户端调用 EMS
| EMS 接口 | URL | 用途 | 触发模块 | 关键字段 |
|---|---|---|---|---|
| 登录 | `POST /north/login` | 鉴权取 token | 连接管理 | 入: ip,port,username,password 出: token |
| 心跳 | `POST /north/heart` | 20s 保活 | 连接管理 | data 空 |
| 登出 | `POST /north/logout` | 释放连接 | 连接管理 | data 空 |
| 获取空间 | `POST /north/get_space_list` | 同步空间树 | 配置同步 | 出: resources[](空间对象) |
| 获取设备 | `POST /north/get_device_list` | 同步设备 | 配置同步 | 出: resources[](设备对象) |
| 获取测点 | `POST /north/get_spot_list` | 同步设备下测点 | 配置同步 | 入: resource_ids[] 出: devices[]{resource_id,points[]} |
| 订阅实时 | `POST /north/online_data_subscribe` | 启动周期推送 | 采集 | 入: subscribe=true |
| 在线拉取 | `POST /north/online_data` | 兜底主动拉取 | 采集 | 入: device_ids[]\|spot_ids[]（互斥） 出: points[] |
| 历史数据 | `POST /north/offline_value` | 趋势/断连回补 | 历史/回补 | 入: start,end,resource_ids[](≤100),interval(five/ten/quarter/twenty/half/hour) 出: [{resource_id,data_list[]{value,time}}] |
| 订阅告警 | `POST /north/online_alarm_subscribe` | 启动告警推送 | 告警接入 | 入: subscribe=true |
| 历史告警 | `POST /north/offline_alarm` | 历史告警查询 | 告警接入 | 入: begin_time,end_time,resource_ids[],event_level[],event_type[],is_recover[],confirm_type[],is_accept[],masked[],cep_processed[] 出: {total,alarm[]} |
| 读规则 | `POST /north/get_event_rules` | 导入规则初值(可选) | 规则 | 入: resource_ids[](≤100) 出: [{resource_id,event_rules[]}] |

> **不实现**：`set_event_rules`（不向 EMS 反向下发规则）、`setting`（纯只读，不下控）。

### B2. 平台作为服务端被 EMS 推送（必须实现）
| 接口 | URL（平台暴露） | 入参 | 平台响应 |
|---|---|---|---|
| 实时数据推送 | `POST /north/online_data_push` | `{period, page_no, page_size, devices[]{resource_id,status,points[]{resource_id,real_value,save_time}}}`（设备无测点时 points=null） | `{"error_code":0,"error_msg":"ok","data":{"status":true}}` |
| 告警推送 | `POST /north/online_alarm_push` | `{alarms[]{guid,resource_id,event_location,event_source,msg_type,masked,event_alarm{...},event_recover{...},event_accept{...},event_confirm{...}}}` | 同上 `status:true` |

> 推送目标 ip:port = login 时平台声明的 recv_ip/recv_port。平台这两个推送端点须挂在该地址上。

### B3. 告警推送结构字段语义
- `msg_type`：0 产生 / 1 恢复 / 2 受理 / 3 确认 —— 决定取 event_alarm / event_recover / event_accept / event_confirm 中的哪个子结构。
- `event_alarm`：event_type、event_snapshot（触发值）、event_level（"1"–"5"）、event_time（Unix 秒）、content、event_suggest。
- `masked`：0 未屏蔽 / 1 已屏蔽。
- **平台处理**：仅接纳 event_type ∈ {0 通信中断, 21 故障, 30 停止采集}（source=ems 入库）；其余阈值类（2/4/3 等）默认丢弃（由平台引擎负责，去重）。

---

## C. 枚举与错误码（对齐《标准 V2.23》）

### C1. 告警级别 event_level
| 值 | 含义 |
|---|---|
| 1 | 紧急严重告警 |
| 2 | 严重告警 |
| 3 | 重要告警 |
| 4 | 次要告警 |
| 5 | 提示 |

### C2. 告警类型 event_type
| 值 | 含义 | 平台是否自管 |
|---|---|---|
| 0 | 通信中断 | EMS 来源 |
| 2 | 过高报警 | 平台引擎 |
| 3 | 不正常值 | 平台引擎 |
| 4 | 过低报警 | 平台引擎 |
| 5 | 错误数据 | 平台引擎 |
| 7 | 事件 | 视配置 |
| 21 | 故障 | EMS 来源 |
| 30 | 停止采集 | EMS 来源 |

### C3. spot_type / ci_type / space_type
- ci_type：2 设备 / 3 测点 / 5 空间。
- spot_type：1 模拟量 / 2 状态量 / 3 控制量。
- space_type：1 区域 / 2 园区 / 3 楼宇 / 4 楼层 / 5 房间 / 6 机柜列 / 7 机柜位 / -1 未知。

### C4. EMS error_code（HTTP 200 时有效）
| code | message | 平台动作 |
|---|---|---|
| 0 | ok | 正常 |
| 1 | abnormal parameter | 记录并告警，检查请求 |
| 2 | abnormal TOKEN | 触发重新登录 |
| 3 | abnormal version | 校正 version 字段 |
| 4 | other error | 记录 error_msg |
| 5 | unknown error | 记录 |
| 100 | user/password wrong | 登录失败，停止重试并提示 |
| 101 | resource_id not exist | 跳过该 ID（注意：一个不存在则整批不返回，回补需保证 ID 有效） |
| 102 | time format error | 校正时间格式 |
| 104 | abnormal value | 记录 |
| 106 | heart timeout | 触发重新登录 + 重订阅 |
