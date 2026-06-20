# 动环监控预警平台 — PRD 交付包

> 自建动环（动力环境）监控预警平台，对接共济 EMS 北向接口（《共济基础设施监控数据接入标准 V2.23》），替代共济自带平台，实现数据自主采集、自定义预警与统一展示。
>
> 本包面向 **AI 编码 Agent（Claude Code）** 编写，所有约束已显式化，可直接据此开发。

---

## 一句话定位

平台扮演共济 EMS 北向协议中的「上层集成平台」角色：作为 HTTP 服务端接收 EMS 推送的实时数据与告警，同时作为 HTTP 客户端完成登录、心跳、配置同步、历史回补；在此之上构建**平台自有规则引擎**做预警，并提供监控大盘、趋势、拓扑、告警中心、大屏与报表。

## 核心边界

| 维度 | 决策 |
|---|---|
| 范围 | **纯监控 + 预警**（无工单 / 巡检 / 排班 / 资产 / 能效 PUE） |
| 数据源 | 单数据中心、单厂商（共济 EMS），百级测点 |
| 取数 | **推送独占**（平台为 EMS 唯一推送消费端），辅以拉取/历史接口 |
| 存储 | 分层：近 30 天原始秒级 + 5min 降采样存满 6 个月 |
| 告警源 | **混合**：平台规则引擎算阈值/逻辑类；EMS 告警仅接设备级事件（通信中断/故障/停采）并去重 |
| 规则引擎 | 基础档：多级静态阈值 + 持续超限去抖 + 自动恢复 + 5 级分级 |
| 下控 | **纯只读**，不实现共济 setting 控制接口 |
| 技术栈 | FastAPI + Vue3/Element Plus/ECharts + PostgreSQL/TimescaleDB + Redis + Docker Compose |
| 部署 | Linux 内网单机 + 定时备份（不做 HA） |
| 安全 | 内部自用从简：内网 + RBAC（三角色）+ 密码哈希 + token 安全（无审计日志、无等保基线） |

## 文件清单与阅读顺序

| 顺序 | 文件 | 内容 |
|---|---|---|
| 1 | `01_PRD_主文档.md` | 背景、范围、角色、功能需求（FR）、非功能需求（NFR）、验收标准 |
| 2 | `02_数据模型与DB_Schema.md` | 实体模型 + PostgreSQL/TimescaleDB 建表 DDL（含降采样/压缩/保留策略） |
| 3 | `03_API规格.md` | 平台自身 REST/WebSocket API + 共济 EMS 北向接口对接映射 + 错误码 |
| 4 | `04_架构与模块目录结构.md` | 系统架构、数据流、后端/前端模块划分、目录结构、Docker Compose |
| 5 | `05_Sprint开发计划.md` | 分阶段 Sprint 任务（Sprint 0–7）及各阶段验收 |
| 6 | `CLAUDE.md` | 给 Claude Code 的项目级开发指令与关键约束 |
| 7 | `06_Claude_Code_启动提示词.md` | 两版可直接粘贴的 Claude Code 启动提示词（分阶段 / 全量连续） |
| 8 | `ems_mock/` | 模拟共济 EMS 服务（FastAPI，可直接联调），含 `README.md` |

## 给 AI Agent 的起步建议

1. 先读 `CLAUDE.md` 与本文件，建立全局约束。
2. 读 `01` 理解需求，读 `04` 理解架构与目录，按 `02`/`03` 落地数据与接口。
3. 按 `05` 的 Sprint 顺序实现；**Sprint 0 即接入 `ems_mock`**，全程对着 mock 联调，无需真实 EMS。
4. 共济协议的所有报文格式以《数据接入标准 V2.23》原文为准，`03_API规格.md` 已提炼关键对接点。

---

# 运行与运维说明

> 面向部署/联调/值守。当前实现已通过 Sprint 0–7 全部验收，并完成一次完整端到端联调（见 `PROGRESS.md` 与 `docs/screenshots/`）。

## 1. 组件与端口

| 服务 | 镜像/构建 | 对外端口 | 说明 |
|---|---|---|---|
| `db` | timescale/timescaledb:latest-pg15 | 内部 5432 | 时序 + 元数据同库；卷 `pgdata` 持久化 |
| `redis` | redis:7-alpine（appendonly） | 内部 6379 | 最新值/状态/Pub-Sub/分布式锁；卷 `redisdata` |
| `backend` | ./backend（FastAPI） | `8000` | 平台 API **与** `/north` 推送接收端点同端口 |
| `frontend` | ./frontend（Vue3 → nginx） | `8080` | SPA + 反代 `/api` 到 backend |
| `ems_mock` | ./ems_mock（联调用） | `9000` | 模拟共济 EMS；无真实 EMS 时启用 |

默认账号：平台 `admin / admin123`（`.env` 可改）；mock 登录 `admin / 123456`。

## 2. 一键部署（Linux 内网单机）

```bash
cp .env.example .env          # 按需改密钥/端口/EMS 连接，生产务必改 JWT_SECRET 与 ENCRYPTION_KEY
make up                       # = docker compose up -d --build
make ps                       # 看五个服务状态
curl -fsS http://localhost:8000/health   # {"status":"ok","components":{"db":"up","redis":"up","ems":...}}
```

- 迁移在 backend 容器启动时自动 `alembic upgrade head`（compose 命令内置）；手动重跑：`make migrate`。
- 前端访问 `http://<host>:8080`，后端 API `http://<host>:8000`。

## 3. 关键配置（`.env`）

| 变量 | 含义 | 备注 |
|---|---|---|
| `JWT_SECRET` / `ENCRYPTION_KEY` | 令牌签名 / EMS 凭据加密 | **生产必须替换**；ENCRYPTION_KEY 为 32 字节 base64（Fernet） |
| `DEFAULT_ADMIN_USERNAME/PASSWORD` | 首启种子管理员 | 首次登录后建议改密 |
| `EMS_BASE_URL` | EMS/mock 地址 | 联调填 `http://ems_mock:9000` |
| `EMS_USERNAME/PASSWORD` | EMS 凭据 | 加密入库 |
| `EMS_RECV_IP/PORT` | 平台**对外可达**的推送接收地址 | compose 内填 `backend`/`8000`；跨机填宿主机 IP，**勿填 127.0.0.1** |
| `EMS_VERSION` | 共济包头 version | 默认 `20170714124155` |
| `EMS_AUTO_CONNECT` | 启动自动登录+订阅 | `true` 时 backend 起后自动重连重订阅 |

> 任何 `.env` 变更需同步 `.env.example`（红线/规范）。

## 4. 联调步骤（对 ems_mock）

启动顺序由 compose 依赖保证。首次或重置后触发同步与订阅：

```bash
# 一键冒烟（登录→同步→校验连接/资产/实时/告警），对已运行栈用 NO_UP=1
make e2e                      # 或 NO_UP=1 bash scripts/e2e_smoke.sh
```

手动驱动（与 UI「系统设置→EMS 连接」等价）：

```bash
TOKEN=$(curl -fsS -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
curl -fsS -X POST http://localhost:8000/api/v1/sync/config -H "Authorization: Bearer $TOKEN"   # 同步空间/设备/测点
curl -fsS http://localhost:8000/api/v1/settings/ems/status -H "Authorization: Bearer $TOKEN"   # state=online 即已订阅推送
```

订阅后 mock 每 **10s** 推送一轮实时数据、周期注入超限（触发平台引擎告警）、周期推送设备级事件（通信中断 0/故障 21/停采 30）。

## 5. 备份与恢复

详见 `docs/运维-备份与恢复.md`。常用：

```bash
make backup                              # pg_dump -Fc → backups/dcim_YYYYMMDD_HHMMSS.dump (+.sha256，自动保留清理)
make restore FILE=backups/xxx.dump       # 校验 sha256 后恢复（会先确认）
```

- 备份为自定义格式（`-Fc`），含时序 hypertable 与连续聚合定义；恢复前自动校验 SHA256。
- 建议用宿主机 cron 每日 `make backup`，并将 `backups/` 同步到异机/外部存储。

## 6. 日常运维与排障

| 现象 | 排查 |
|---|---|
| `/health` 中 `ems` 非 online | 看 `settings/ems/status` 的 `reconnects`/`token_ok`；确认 mock/真实 EMS 可达、`EMS_RECV_IP` 对 EMS 侧可达 |
| 收不到推送（last_push 不前进） | 平台触发了订阅吗？`EMS_RECV_IP/PORT` 是否被 EMS 反向访问；看 backend 日志 `ingest` |
| 断连后未回补 | 缺口阈值 45s、巡检每 22s；EMS 需先重连（持 token）才回补；看 `sync/log` 的 `kind=backfill` |
| 告警未通知 | 是否配置了对应级别的 `notify/routes` + 渠道 + 接收组；看 `notify/logs` 的 `status` |
| 平台引擎不告警 | 是否在「预警规则」配置了对应测点阈值规则（`/api/v1/rules`）；规则缓存 30s TTL |

```bash
make logs                                       # 跟踪 backend 日志（按模块：采集/规则/通知/同步）
docker compose exec redis redis-cli hgetall ems:conn   # EMS 连接实时状态
docker compose restart backend                  # 重启后端（EMS_AUTO_CONNECT 会自动重登重订阅）
```

## 7. 质量门禁（本地）

```bash
# 后端：安装运行+测试依赖（测试栈在 requirements-dev.txt：pytest-asyncio/fakeredis/respx/aiosqlite）
cd backend && uv pip install -r requirements-dev.txt
uv run ruff check . && uv run pyright && uv run pytest -q   # lint + 类型 + 离线确定性测试（无外网/无 EMS/无密钥）
# 前端
cd frontend && bun install && bun x tsc --noEmit && biome check .
```

当前后端门禁：ruff 通过、pyright 0 error、pytest 126 passed（含规则引擎去抖/恢复、回补串行、
告警过滤去重、通知失败语义、安全 fail-fast 等行为级测试）。
