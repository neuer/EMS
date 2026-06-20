# Sprint 开发计划

按依赖顺序推进。每个 Sprint 结束须对照「验收」自测。**Sprint 0 即接入 `ems_mock`，全程对 mock 联调，无需真实 EMS。**

---

## Sprint 0 · 项目骨架与联调底座
**任务**
- 初始化仓库：backend(FastAPI) + frontend(Vue3+Vite) + docker-compose(db/redis/backend/frontend)。
- 集成 PostgreSQL+TimescaleDB；用 Alembic 落 `02_数据模型` 的全部 DDL（hypertable/连续聚合/压缩/保留策略）。
- core 基建：config(.env)、DB 会话、Redis、JWT/RBAC、加密、结构化日志、`/health`。
- 启动 `ems_mock`，验证 backend 能访问其 `/north/*`。

**验收**：`docker compose up` 一键起栈；DB 迁移成功且 hypertable/连续聚合存在；健康检查通过；mock 可访问。

---

## Sprint 1 · EMS 连接管理 + 配置同步 + 实时采集
**任务**
- `ems/client.py`：封装 login/heart/logout/get_space_list/get_device_list/get_spot_list/online_data（统一包头、token、error_code 处理）。
- `ems/connection.py`：登录取 token → 20s 心跳任务 → 异常/106/2 退避重连 → 重订阅；状态写 `ems:conn`。
- `ems/push_server.py`：实现 `/north/online_data_push` 并返回 status:true。
- `sync/config_sync.py`：全量同步空间/设备/测点树 + 增量比对 + inactive 标记；手动 `/sync/config`。
- `ingest/realtime.py`：解析推送 → Redis 最新值 + device_status + Pub/Sub → 落 `point_history`。
- 订阅 `online_data_subscribe`。

**验收**：登录并维持心跳；断 mock 再起能自动重连；同步出完整资产树；持续接收 10s 推送并落库；`/realtime/points` 取到最新值；`/settings/ems/status` 正确。

---

## Sprint 2 · 历史数据 + 分层 + 断连回补
**任务**
- `history/query.py`：`/history/query` 按范围选层（raw/5min/auto）；多测点。
- 验证连续聚合 5min 与 30 天/6 个月保留、压缩生效。
- `history/backfill.py`：检测推送中断→恢复后用 `offline_value` 回补；严格 ≤100 测点/≤1 天/串行(锁)/分批分片；写降采样层 + 缺口标记 + `sync_log`。
- WebSocket 网关 `/ws/realtime` 订阅推送最新值到前端。

**验收**：长短范围趋势查询分别命中降采样/原始层；人为停推一段时间后恢复，缺口被正确回补且不违反接口限制；前端 WS 实时刷新。

---

## Sprint 3 · 规则引擎 + 告警生命周期 + 抑制
**任务**
- `engine/rules.py`：消费实时值；多档静态阈值(> < = <> <= >= / 区间)；continuous_time 去抖；restore 条件 + recover_hold 自动恢复；5 级分级；同点多档取最高。
- `engine/lifecycle.py`：状态机(active→accepted→confirmed→recovered / 直达 recovered)；alarms + alarm_events；受理/确认/备注 API。
- `engine/suppress.py`：测点屏蔽、维护窗口静默、防轰炸合并(merge_key + 合并窗口 + 计数)。
- 告警接入：`/north/online_alarm_push` + 订阅；仅纳 event_type∈{0,21,30}，阈值类去重。
- 告警中心 API（active/history/detail/accept/confirm/note/stats）。

**验收**：配置多档规则触发→去抖生效、分级正确、生命周期可流转；屏蔽/维护窗口内不误扰；同点高频告警被合并；EMS 通信中断/故障/停采进入告警中心，阈值类 EMS 告警被去重。

---

## Sprint 4 · 通知
**任务**
- `notify/dispatcher.py`：按 level 路由→渠道集合+接收组→解析接收人→发送→失败重试→`notify_logs`；遵循防轰炸合并（首发+周期摘要）。
- `notify/channels/`：sms(对接内部短信平台)/email/dingtalk/wecom/voice/webhook 适配器 + 渠道连通测试。
- 通知配置 API（渠道/接收人/组/级别路由）。

**验收**：不同级别告警按映射发对渠道；短信经内部平台发出；恢复通知按级别开关；合并窗口内不轰炸；发送记录与重试可见；渠道测试可用。

---

## Sprint 5 · 核心展示
**任务**
- 实时大盘（KPI 卡片 + 关键测点 WS 刷新 + 区域状态）。
- 设备/测点列表 + 测点详情（当前值/单位/规则/元数据/实时+历史曲线，筛选搜索）。
- 历史趋势查询页（多测点叠加、快捷时间、自动选层、导出 CSV）。
- 空间拓扑导航（空间树下钻，节点叠加告警状态）。
- 告警中心页（活动/历史、筛选、受理/确认/备注、生命周期流）。
- 元数据增强管理界面。

**验收**：以上页面功能完整、数据正确、实时刷新；筛选/搜索/钻取可用；告警处理闭环。

---

## Sprint 6 · 大屏 + 移动端 + 报表
**任务**
- NOC 值班大屏（深色全屏、大字号、实时告警滚动、级别统计、关键曲线、轮播、自适应分辨率）。
- 移动端响应式（大盘/告警中心/测点详情）。
- 报表：告警统计(日/周/月) + 数据/告警导出(CSV/Excel) + 定时邮件报表计划(APScheduler)。

**验收**：大屏适配值班墙；手机端可查看与处理告警；统计报表与导出正确；定时邮件报表按计划发出。

---

## Sprint 7 · 权限收尾 + 系统设置 + 加固
**任务**
- RBAC 三角色全面落地（菜单/接口/按钮级；readonly 只读）。
- 系统设置闭环：EMS 连接配置(密码加密/脱敏)、规则管理、通知配置、维护窗口、用户管理、报表计划、死区存储开关。
- 备份脚本与恢复文档；时区/日志统一复核；纯只读复核（确认对 EMS 无任何写调用）；端到端联调脚本。

**验收**：权限边界正确；设置项全部可用并持久化；备份恢复演练通过；`01_PRD 第 8 节` 所有验收项通过；全栈对 `ems_mock` 端到端跑通。

---

## 里程碑
- **MVP（Sprint 0–3）**：接入 + 采集 + 存储 + 预警闭环（可看数据、能出告警）。
- **可用版（+4–5）**：通知 + 核心展示（值班可用）。
- **完整版（+6–7）**：大屏/移动端/报表 + 权限设置加固。
