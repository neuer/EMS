# Claude Code 启动提示词

两版可直接复制粘贴的启动提示词。**先把整个 PRD 包目录放进 Claude Code 的项目根目录**,再粘贴对应提示词。

- **版本 A · 分阶段(Sprint checkpoint)**:每完成一个 Sprint 停下汇报,等你确认再继续。适合你想逐阶段把关、边看边调。
- **版本 B · 全量连续构建**:从 Sprint 0 一口气做到可运行,中途不停。适合让它自主把 MVP/完整版跑出来。

> 实操提醒:版本 B 需要给 Claude Code 开**自动执行权限**(能跑 docker / alembic / 测试),否则无法走联调闸门完成自测。

---

## 版本 A · 分阶段(Sprint checkpoint)

```text
你是本项目的主力开发。仓库根目录已放入完整 PRD 包,据此从零构建「动环监控预警平台」。

【第一步 · 读文档(按序)】
先读 CLAUDE.md 和 README.md 建立全局约束与边界,再读 01_PRD_主文档.md(需求)、
04_架构与模块目录结构.md(架构/目录)、02_数据模型与DB_Schema.md(DDL)、
03_API规格.md(接口)、05_Sprint开发计划.md(分阶段任务)。
ems_mock/ 是模拟共济 EMS,全程用它联调,不依赖真实 EMS。

【项目定位】
对接共济 EMS 北向接口(《数据接入标准 V2.23》)自建上层动环监控预警平台。范围仅监控+预警。
单数据中心、百级测点。技术栈:FastAPI + Vue3/Element Plus/ECharts + PostgreSQL/TimescaleDB + Redis + Docker Compose。

【红线 · 必须遵守,违反即错】
1. 纯只读对接 EMS:绝不实现/调用 setting(下控)与 set_event_rules(反向下发规则)。
2. 推送独占:实现 /north/online_data_push 与 /north/online_alarm_push 两个接收端点,
   返回 {"data":{"status":true}},挂在 login 上报的 recv_ip:recv_port。
3. 共济报文严格遵循:请求含包头 {"version":...,"data":{...}};响应 {"error_code":0,"error_msg":"ok","data":{...}};
   除 login 外 Header 带 token。
4. 心跳每 20s;遇 error_code 2/106 或心跳失败→重新登录并重订阅 data+alarm,指数退避。
5. offline_value 单次 ≤100 测点、≤1 天、串行(Redis 锁);趋势查询与断连回补都遵守,回补按测点分批+按时间分片。
6. 存储分层:原始 hypertable 保留 30 天 + 5min 连续聚合保留 6 个月,查询按时间范围自动选层。
7. 混合告警源:平台规则引擎负责阈值/逻辑类;EMS 告警只纳 event_type∈{0,21,30},其余阈值类去重丢弃。
8. 元数据写 asset_meta 不污染源;安全内部从简(内网+RBAC三角色+bcrypt+凭据加密,无审计、无等保);
   时间统一 Unix 秒→TIMESTAMPTZ;界面与代码注释用中文。

【怎么干】
- 严格按 04 的目录结构与模块边界落地,不要堆单文件、不要自行更换技术栈或架构。
- 按 05 的 Sprint 顺序推进。现在只做 Sprint 0:
  初始化 backend(FastAPI)+ frontend(Vue3+Vite)+ docker-compose(db/redis/backend/frontend);
  用 Alembic 落 02 的全部 DDL(含 hypertable / 连续聚合 / 压缩 / 保留策略);
  搭好 core 基建(config+.env、DB 会话、Redis、JWT+RBAC、加密、结构化日志、/health);
  确认 backend 能访问 ems_mock。
- Sprint 0 完成后停下,给我:实际创建的文件清单、docker compose up 自测结果、遇到的问题;
  等我确认再进入 Sprint 1。

开始前,先用一段话复述你对项目边界与上述红线的理解,再动手。
```

---

## 版本 B · 全量连续构建

```text
你是本项目的主力开发,采用自主连续开发模式:一次性把平台从零构建到可运行,中途不逐阶段征询。
仓库根目录已放入完整 PRD 包。

【第一步 · 读文档(按序)】
先读 CLAUDE.md 和 README.md 建立全局约束与边界,再读 01_PRD_主文档.md(需求)、
04_架构与模块目录结构.md(架构/目录)、02_数据模型与DB_Schema.md(DDL)、
03_API规格.md(接口)、05_Sprint开发计划.md(分阶段)。
ems_mock/ 是模拟共济 EMS,全程用它联调,不依赖真实 EMS。

【项目定位】
对接共济 EMS 北向接口(《数据接入标准 V2.23》)自建上层动环监控预警平台,范围仅监控+预警,
单数据中心、百级测点。栈:FastAPI + Vue3/Element Plus/ECharts + PostgreSQL/TimescaleDB + Redis + Docker Compose。

【红线 · 必须遵守,违反即错】
1. 纯只读对接 EMS:绝不实现/调用 setting(下控)与 set_event_rules(反向下发规则)。
2. 推送独占:实现 /north/online_data_push 与 /north/online_alarm_push 两个接收端点,
   返回 {"data":{"status":true}},挂在 login 上报的 recv_ip:recv_port。
3. 共济报文严格遵循:请求含包头 {"version":...,"data":{...}};响应 {"error_code":0,"error_msg":"ok","data":{...}};
   除 login 外 Header 带 token。
4. 心跳每 20s;遇 error_code 2/106 或心跳失败→重新登录并重订阅 data+alarm,指数退避。
5. offline_value 单次 ≤100 测点、≤1 天、串行(Redis 锁);趋势查询与断连回补都遵守,回补按测点分批+按时间分片。
6. 存储分层:原始 hypertable 保留 30 天 + 5min 连续聚合保留 6 个月,查询按时间范围自动选层。
7. 混合告警源:平台规则引擎负责阈值/逻辑类;EMS 告警只纳 event_type∈{0,21,30},其余阈值类去重丢弃。
8. 元数据写 asset_meta 不污染源;安全内部从简(内网+RBAC三角色+bcrypt+凭据加密,无审计、无等保);
   时间统一 Unix 秒→TIMESTAMPTZ;界面与代码注释用中文。

【怎么干 · 全量连续构建】
- 严格按 04 的目录结构与模块边界落地,不堆单文件、不换技术栈或架构。
- 按 05 的 Sprint 顺序从 Sprint 0 连续推进到 Sprint 7,中途不停下等确认,实现细节自主决策。
- 优先级:先把 MVP(Sprint 0–3:接入+采集+存储+预警闭环)做到完整可运行,再继续 4–7(通知/展示/大屏移动端报表/权限设置)。
- 每完成一个 Sprint:① 对照该 Sprint 的"验收"逐项自测并修复;② git commit(注明 Sprint N + 完成项);
  ③ 更新仓库根目录 PROGRESS.md(已完成 / 进行中 / 待办 清单)。
- 关键路径必须有测试:阈值去抖、自动恢复、防轰炸合并、断连回补的分批/分片/串行、混合告警源去重。
- 联调闸门:用 ems_mock 跑通端到端冒烟——登录→配置同步→订阅→持续收到 10s 推送→注入超限触发平台告警→
  按级别通知→设备级事件(0/21/30)进告警中心;冒烟不过不算该阶段完成。
- 自主决策:实现取舍自己定并在 PROGRESS.md 记录;仅当与 PRD 冲突或真正阻塞时才停,
  且停前写清"已完成 / 受阻原因 / 我的建议方案"。
- 若因篇幅/时长无法一次跑完:保证当前 Sprint 完整可运行,MVP 优先落地,并在 PROGRESS.md 留清晰续作指引。

开始前,先用一段话复述项目边界与红线,并列出你的 Sprint 推进计划与里程碑,然后连续动手到底。
```
