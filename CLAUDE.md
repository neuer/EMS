# CLAUDE.md — 动环监控预警平台

本文件是给 Claude Code 的项目级指令。开发前先读 `README.md` 与 `01_PRD_主文档.md`，本文件聚焦「怎么干」与「红线」。

## 项目一句话
对接共济 EMS 北向接口（《共济基础设施监控数据接入标准 V2.23》），自建上层动环监控预警平台。平台是 EMS 推送的唯一消费端，纯只读，单数据中心、百级测点。范围仅监控 + 预警。

## 技术栈（已定，勿擅自更换）
- 后端：Python + FastAPI（async）、SQLAlchemy、Pydantic、Alembic、APScheduler、httpx、redis-py。
- 前端：Vue 3 + Vite + TypeScript + Element Plus + ECharts + Pinia + axios。
- 存储：PostgreSQL 15 + TimescaleDB（时序与元数据同库）。
- 中间件：Redis（最新值/状态/Pub-Sub/分布式锁）。
- 部署：Docker Compose，Linux 内网单机。

## 关键约束（红线，违反即错）
1. **纯只读对接 EMS**：绝不实现也绝不调用 `setting`（下控）与 `set_event_rules`（反向下发规则）。平台对 EMS 只有读和订阅。
2. **推送独占**：平台是 EMS 唯一推送端；推送目标为 login 时声明的 recv_ip/recv_port，backend 必须对外暴露 `/north/online_data_push` 与 `/north/online_alarm_push` 并返回 `{"data":{"status":true}}`。
3. **共济报文格式严格遵循**：请求体含包头 `{"version": "<version_str>", "data": {...}}`；响应体 `{"error_code":0,"error_msg":"ok","data":{...}}`；UTF-8；空值键必须保留。除 login 外所有客户端请求 Header 带 `token`。
4. **心跳**：登录后每 20s 调 `/north/heart`；遇 error_code 2/106 或心跳失败→重新登录并重订阅 data+alarm；指数退避。
5. **历史接口限制**：`offline_value` 单次 ≤100 测点、跨度 ≤1 天、同一时间仅一个历史请求在跑。趋势查询与断连回补都要遵守——回补按测点分批 + 按时间分片 + 串行(用 Redis 锁 `lock:history`)。
6. **存储分层**：原始层 `point_history`(hypertable, 30 天, 压缩)；降采样层 `point_history_5min`(连续聚合 5min, 6 个月)。趋势查询按范围自动选层。
7. **混合告警源**：平台规则引擎算阈值/逻辑类；EMS 告警只纳 `event_type ∈ {0 通信中断, 21 故障, 30 停止采集}`，其余阈值类（2/4/3）默认丢弃去重。
8. **元数据不污染源**：EMS 同步对象只读镜像；别名/分组/标签/重要度/单位写在 `asset_meta`，按 resource_id 关联。
9. **安全从简但不裸奔**：仅内网；密码 bcrypt；EMS 凭据加密入库；JWT/RBAC 三角色；不做审计日志、不做等保基线。
10. **时间统一**：共济一律 Unix 秒（save_time/period/event_time）；入库转 TIMESTAMPTZ(UTC)，按本地时区展示。

## 联调（重要）
- 真实 EMS 不一定可用；**全程对着 `ems_mock` 开发**。
- mock 实现了全部北向接口，并能在订阅后按 10s 周期向平台推送实时数据、按需推送告警（含会触发阈值的数据，便于验证规则引擎）。
- 启动顺序：起 db/redis → 起 backend(含 /north 推送端点) → 起 ems_mock 并指向 backend 的 recv 地址 → 平台配置 EMS 连接指向 mock → 触发同步与订阅。详见 `ems_mock/README.md`。

## 开发约定
- 后端模块边界与目录见 `04_架构与模块目录结构.md`，按该结构落地，勿堆单文件。
- 所有对 EMS 的调用集中在 `ems/client.py`，错误码与包头逻辑只在一处处理。
- 规则引擎、生命周期、抑制、通知解耦，便于单测；防轰炸/去抖/恢复要有针对性测试。
- 配置集中 `.env`（DB/Redis/JWT 密钥/加密密钥/默认管理员）。
- 输出中文界面与中文注释；日志按模块（采集/规则/通知/同步）分类。
- 每个 Sprint 完成对照 `05` 的验收自测，并补关键路径测试。

## 不要做
工单/巡检/排班/资产/PUE/多中心/多厂商/下控/向 EMS 写规则/审计日志/等保基线/浏览器 localStorage 持久化业务数据。
