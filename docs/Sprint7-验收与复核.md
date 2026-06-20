# Sprint 7 — 权限收尾 + 系统设置 + 加固｜验收与复核记录

日期：2026-06-20

## 1. 纯只读复核（红线 #1，最高优先）

通读全仓库（`backend/app`、`ems_mock`、`frontend/src`）确认平台对 EMS **绝无任何写调用**：

- `ems/client.py` 仅封装只读/订阅端点：`login / heart / logout / get_space_list / get_device_list / get_spot_list / online_data_subscribe / online_alarm_subscribe / online_data / offline_value`。
- 全仓搜索 `set_event_rules` / `/north/setting` / `setting(` 仅命中**禁用声明注释**（`ems/client.py`、`ems/__init__.py`），无任何实现或调用。
- `ems/push_server.py` 仅暴露两个**接收**端点 `/north/online_data_push`、`/north/online_alarm_push`，均返回 `{"data":{"status":true}}`。

结论：**通过**。平台对 EMS 只有读与订阅，无 `setting`（下控）、无 `set_event_rules`（反向下发规则）。

## 2. RBAC 三角色边界（菜单 / 接口 / 按钮级）

| 能力 | admin | operator | readonly | 后端守卫 |
|---|---|---|---|---|
| 查看监控/趋势/告警/报表 | ✓ | ✓ | ✓ | `get_current_user` |
| 受理/确认/备注告警 | ✓ | ✓ | ✕ | `require_role(OPERATOR)` |
| 维护窗口 / 测点屏蔽 | ✓ | ✓ | ✕ | `require_role(OPERATOR)` |
| 元数据增强写入 | ✓ | ✓ | ✕ | `require_role(OPERATOR)` |
| 规则管理 | ✓ | ✕ | ✕ | `require_role(ADMIN)` |
| 通知配置 | ✓ | ✕ | ✕ | `require_role(ADMIN)` |
| EMS 连接配置 | ✓ | ✕ | ✕ | `require_role(ADMIN)` |
| 用户与角色管理 | ✓ | ✕ | ✕ | `require_role(ADMIN)` |
| 报表计划 | ✓ | ✕ | ✕ | `require_role(ADMIN)` |

- **接口级**：后端每个写端点均挂 `require_role`，访问控制在后端强制执行（红线 #9）。
- **菜单级**：`MainLayout` 系统设置子菜单按角色过滤（readonly 无任何设置项；operator 仅「维护/屏蔽」；admin 全部）。
- **路由级**：`router.beforeEach` 按 `meta.role` 守卫，权限不足回退大盘。
- **按钮级**：各页写操作按钮以 `auth.canWrite` / `auth.isAdmin` 显隐（前端仅显隐，后端仍校验）。
- **用户管理不变量**（纯函数 `will_keep_an_admin`，离线单测覆盖）：不可删除/降级/禁用「最后一个启用的管理员」；不可删除/禁用当前登录账户。

## 3. EMS 凭据加密与脱敏（红线 #8）

- 写入：`PUT /settings/ems` 提供 `password` 时经 `core.crypto.encrypt`（Fernet）加密入库；留空则保留原值。
- 读取：`GET /settings/ems` 固定返回 `password_masked="********"`，从不回传明文/密文。
- 通知渠道敏感配置同样加密入库、读时脱敏（`notify/config_crypto.py`：`encrypt_config/mask_config/apply_config_update`）。
- 前端 EMS 配置页密码框留空表示「不修改」，不回显任何凭据。

## 4. 时区 / 日志统一复核（红线 #10）

- 容器时区：`docker-compose.yml` 中 `db` 与 `backend` 均设 `TZ=${TZ:-Asia/Shanghai}`。
- 入库：EMS 一律 Unix 秒（save_time/period/event_time）；`ingest/realtime.py:_to_utc` 以 `datetime.fromtimestamp(int(save_time), tz=UTC)` 转 TIMESTAMPTZ(UTC)。
- 日志：`core/logging.py` 输出单行 JSON，`ts` 为 UTC ISO，按模块命名（采集/规则/通知/同步），含 `extra_fields` 结构化字段，无不可解析长字符串。
- 展示：前端按浏览器本地时区渲染（`toLocaleString`）。

## 5. 质量门禁结果

| 门禁 | 命令 | 结果 |
|---|---|---|
| 后端 Lint | `ruff check app tests` | 通过（0） |
| 后端类型 | `pyright app tests` | 0 errors |
| 后端测试 | `pytest` | 全部通过 |
| 前端类型 | `vue-tsc --noEmit` | 0（exit 0） |
| 前端构建 | `bun run build` | 成功 |

> 加固附带修复：升级版工具链（ruff 0.15 / pyright 1.1.408）暴露的既有类型/规范漂移已一并清理（`timezone.utc→datetime.UTC`、`Generic`→PEP695、`Sequence/list`、SQLAlchemy/redis 存根类型等），均为类型/格式层面的行为保持变更。

## 6. PRD 第 8 节验收映射

| 验收项 | 状态 | 说明 |
|---|---|---|
| 登录/心跳/重连/状态页 | 既有(S1) + 设置页状态可视 | 设置→EMS 连接展示状态/心跳/推送/重连 |
| 配置同步与元数据呈现/手动刷新 | 既有(S1/S5) | — |
| 10s 推送/实时刷新/分层存储 | 既有(S1/S2) | — |
| 断连回补不超限 | 既有(S2) | — |
| 多档规则/去抖/分级/生命周期/路由/合并/维护屏蔽 | 既有(S3/S4) + 本期 UI | 规则/通知/抑制设置页 |
| EMS 设备级事件入中心、阈值类去重 | 既有(S3) | — |
| **三角色权限边界正确；纯只读无写调用** | **本期完成** | 见 §1、§2 |
| 全套视图 + 大屏/移动端/报表 | 既有(S5/S6) | — |
| `docker compose up` 对接 ems_mock 联调 | 本期脚本 | `scripts/e2e_smoke.sh` / `make e2e` |

## 7. 备份与恢复

见 `docs/运维-备份与恢复.md`；脚本 `scripts/backup.sh` / `scripts/restore.sh`；命令 `make backup` / `make restore FILE=...`。
