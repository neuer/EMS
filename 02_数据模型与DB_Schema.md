# 数据模型与数据库 Schema

引擎：PostgreSQL 15+ 与 TimescaleDB 扩展（时序与元数据同库）。下文 DDL 可直接作为迁移初稿，字段名/类型可由实现微调，但语义需保持一致。

---

## 1. 实体总览

| 分组 | 表 | 说明 |
|---|---|---|
| EMS 同步对象 | `spaces` / `devices` / `points` | 从共济同步的空间/设备/测点树（只读镜像） |
| 元数据增强 | `asset_meta` | 平台侧叠加的别名/分组/标签/重要度/单位（不污染源） |
| 时序数据 | `point_history`（hypertable）/ `point_history_5min`（连续聚合） | 原始层 30 天 + 降采样层 6 个月 |
| 实时态 | `device_status` | 设备最新通信状态（最新值缓存在 Redis，不入主表） |
| 预警规则 | `alarm_rules` | 平台规则引擎规则（多档阈值） |
| 告警 | `alarms` / `alarm_events` | 告警主记录 + 生命周期事件流 |
| 抑制 | `point_mute` / `maintenance_windows` | 屏蔽 + 维护窗口 |
| 通知 | `notify_channels` / `recipients` / `recipient_groups` / `recipient_group_members` / `notify_routes` / `notify_logs` | 渠道/接收人/组/级别路由/发送记录 |
| 系统 | `users` / `ems_config` / `report_schedules` / `sync_log` / `system_settings` | 用户、EMS 连接、报表计划、同步日志、全局配置 |

ci_type：5 空间 / 2 设备 / 3 测点；spot_type：1 模拟量 / 2 状态量 / 3 控制量。

---

## 2. DDL

```sql
-- 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ========== 2.1 EMS 同步对象 ==========
CREATE TABLE spaces (
    resource_id   VARCHAR(64) PRIMARY KEY,           -- 共济全局ID
    name          VARCHAR(128) NOT NULL,
    parent_id     VARCHAR(64),
    location      TEXT,                               -- 共济空间路径 project_root/...
    space_type    SMALLINT,                           -- 1区域 2园区 3楼宇 4楼层 5房间 6机柜列 7机柜位 -1未知
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,      -- 同步消失则置false
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_spaces_parent ON spaces(parent_id);

CREATE TABLE devices (
    resource_id   VARCHAR(64) PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    device_type   VARCHAR(64),                        -- 共济自定义设备类型字符串
    parent_id     VARCHAR(64),                        -- 所属空间 resource_id
    location      TEXT,
    link          TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_devices_parent ON devices(parent_id);

CREATE TABLE points (
    resource_id   VARCHAR(64) PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    device_id     VARCHAR(64) NOT NULL,               -- 父设备 resource_id
    spot_type     SMALLINT,                           -- 1模拟量 2状态量 3控制量
    unit          VARCHAR(64),
    mapper        TEXT,                               -- DI/DO 取值含义 "1=开门;0=关门"
    access        VARCHAR(8),                         -- r/w/rw/unkown
    raw_filter    TEXT,                               -- 共济 filter 原始串
    raw_event_rules TEXT,                             -- 共济 event_rules 原始串(导入参考)
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_points_device ON points(device_id);

-- ========== 2.2 元数据增强（本地，不污染源） ==========
CREATE TABLE asset_meta (
    resource_id   VARCHAR(64) PRIMARY KEY,            -- 关联 space/device/point
    asset_kind    SMALLINT NOT NULL,                  -- 5空间 2设备 3测点
    alias         VARCHAR(128),                       -- 别名
    group_name    VARCHAR(128),                       -- 自定义分组
    tags          TEXT[],                             -- 标签
    importance    SMALLINT,                           -- 重要度 1-5
    custom_unit   VARCHAR(64),                        -- 自定义单位(覆盖展示)
    remark        TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_meta_group ON asset_meta(group_name);
CREATE INDEX idx_meta_tags ON asset_meta USING GIN(tags);

-- ========== 2.3 时序数据 ==========
-- 原始层（保留30天）
CREATE TABLE point_history (
    point_id    VARCHAR(64) NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,                 -- 由 save_time(Unix秒) 转换
    value       DOUBLE PRECISION,                     -- 数值型实时值
    PRIMARY KEY (point_id, ts)
);
SELECT create_hypertable('point_history', 'ts', chunk_time_interval => INTERVAL '1 day');

-- 压缩（7天前的块压缩）
ALTER TABLE point_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'point_id',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('point_history', INTERVAL '7 days');

-- 原始层保留 30 天
SELECT add_retention_policy('point_history', INTERVAL '30 days');

-- 降采样层（5分钟连续聚合，保留6个月）
CREATE MATERIALIZED VIEW point_history_5min
WITH (timescaledb.continuous) AS
SELECT
    point_id,
    time_bucket(INTERVAL '5 minutes', ts) AS bucket,
    avg(value) AS avg_value,
    min(value) AS min_value,
    max(value) AS max_value,
    count(*)   AS sample_count
FROM point_history
GROUP BY point_id, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy('point_history_5min',
    start_offset => INTERVAL '1 day',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes');

-- 降采样层保留 6 个月（对连续聚合物化视图设置保留）
SELECT add_retention_policy('point_history_5min', INTERVAL '180 days');

-- 设备最新通信状态（实时值缓存在 Redis，仅状态落库便于历史追溯）
CREATE TABLE device_status (
    device_id   VARCHAR(64) PRIMARY KEY,
    status      SMALLINT NOT NULL,                    -- 0通信中断 1正常
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========== 2.4 预警规则 ==========
CREATE TABLE alarm_rules (
    id                BIGSERIAL PRIMARY KEY,
    point_id          VARCHAR(64) NOT NULL REFERENCES points(resource_id),
    name              VARCHAR(128),
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    -- 触发条件
    operator          VARCHAR(4) NOT NULL,            -- > < = <> <= >=
    operand           DOUBLE PRECISION,               -- 阈值；区间用 operand_min/max
    operand_min       DOUBLE PRECISION,
    operand_max       DOUBLE PRECISION,
    cond_type         VARCHAR(16) NOT NULL DEFAULT 'threshold', -- threshold|range
    -- 恢复条件
    restore_operator  VARCHAR(4),
    restore_operand   DOUBLE PRECISION,
    -- 去抖与恢复
    continuous_time   INTEGER NOT NULL DEFAULT 0,     -- 持续超限秒数(去抖)
    recover_hold_time INTEGER NOT NULL DEFAULT 0,     -- 恢复保持秒数
    -- 分级
    level             SMALLINT NOT NULL,              -- 1紧急 2严重 3重要 4次要 5提示
    -- 多档：同一测点多条规则不同 level + 不同 operand 即构成多档
    priority          SMALLINT NOT NULL DEFAULT 0,    -- 同点多档命中时取最高
    content_tpl       TEXT,                           -- 告警内容模板
    suggest           TEXT,                           -- 处理建议
    created_by        BIGINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rules_point ON alarm_rules(point_id) WHERE enabled;

-- ========== 2.5 告警 ==========
CREATE TABLE alarms (
    id              BIGSERIAL PRIMARY KEY,
    source          VARCHAR(16) NOT NULL,             -- platform | ems
    guid            VARCHAR(80),                      -- EMS告警唯一标识(ems来源时)
    rule_id         BIGINT REFERENCES alarm_rules(id),-- platform来源时
    resource_id     VARCHAR(64) NOT NULL,             -- 关联测点或设备
    resource_kind   SMALLINT NOT NULL,                -- 3测点 2设备
    event_type      SMALLINT,                         -- 0通信中断 2过高 3不正常 4过低 5错误 7事件 21故障 30停采
    level           SMALLINT NOT NULL,                -- 1-5
    status          VARCHAR(16) NOT NULL DEFAULT 'active', -- active|accepted|confirmed|recovered
    trigger_value   DOUBLE PRECISION,                 -- 触发快照值
    content         TEXT,
    suggest         TEXT,
    masked          BOOLEAN NOT NULL DEFAULT FALSE,   -- 是否处于屏蔽/静默
    silenced_reason VARCHAR(32),                      -- mute|maintenance|null
    -- 防轰炸
    merge_key       VARCHAR(160),                     -- point_id+rule 合并键
    merge_count     INTEGER NOT NULL DEFAULT 1,
    -- 时间
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at     TIMESTAMPTZ,
    accepted_by     BIGINT,
    accept_note     TEXT,
    confirmed_at    TIMESTAMPTZ,
    confirmed_by    BIGINT,
    confirm_note    TEXT,
    recovered_at    TIMESTAMPTZ,
    recover_desc    TEXT
);
CREATE INDEX idx_alarms_status ON alarms(status);
CREATE INDEX idx_alarms_resource ON alarms(resource_id);
CREATE INDEX idx_alarms_triggered ON alarms(triggered_at DESC);
CREATE INDEX idx_alarms_mergekey_active ON alarms(merge_key) WHERE status = 'active';

-- 生命周期事件流（产生/受理/确认/恢复及备注）
CREATE TABLE alarm_events (
    id          BIGSERIAL PRIMARY KEY,
    alarm_id    BIGINT NOT NULL REFERENCES alarms(id) ON DELETE CASCADE,
    event       VARCHAR(16) NOT NULL,                 -- raise|accept|confirm|recover|note|merge
    operator_id BIGINT,                               -- 操作人(人工事件)
    note        TEXT,
    snapshot    DOUBLE PRECISION,                     -- 该事件时刻值快照
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alarm_events_alarm ON alarm_events(alarm_id, occurred_at);

-- ========== 2.6 抑制 ==========
CREATE TABLE point_mute (
    id          BIGSERIAL PRIMARY KEY,
    point_id    VARCHAR(64) NOT NULL,
    reason      TEXT,
    start_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    end_at      TIMESTAMPTZ,                          -- null 表示长期屏蔽
    created_by  BIGINT,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_mute_point ON point_mute(point_id) WHERE enabled;

CREATE TABLE maintenance_windows (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(128),
    scope_kind   SMALLINT NOT NULL,                   -- 5空间 2设备 3测点
    scope_ids    TEXT[] NOT NULL,                     -- 适用范围 resource_id 列表
    start_at     TIMESTAMPTZ NOT NULL,
    end_at       TIMESTAMPTZ NOT NULL,
    record_silenced BOOLEAN NOT NULL DEFAULT TRUE,    -- 窗口内是否仍记录为静默告警
    created_by   BIGINT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_maint_time ON maintenance_windows(start_at, end_at);

-- ========== 2.7 通知 ==========
CREATE TABLE notify_channels (
    id          BIGSERIAL PRIMARY KEY,
    type        VARCHAR(16) NOT NULL,                 -- sms|email|dingtalk|wecom|voice|webhook
    name        VARCHAR(64) NOT NULL,
    config      JSONB NOT NULL,                       -- 渠道参数(网关/密钥/webhook url 等，敏感字段加密)
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE recipients (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(64) NOT NULL,
    phone       VARCHAR(32),
    email       VARCHAR(128),
    dingtalk_id VARCHAR(64),
    wecom_id    VARCHAR(64),
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE recipient_groups (
    id    BIGSERIAL PRIMARY KEY,
    name  VARCHAR(64) NOT NULL
);
CREATE TABLE recipient_group_members (
    group_id     BIGINT NOT NULL REFERENCES recipient_groups(id) ON DELETE CASCADE,
    recipient_id BIGINT NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, recipient_id)
);

-- 按级别路由：level -> 渠道集合 + 接收组
CREATE TABLE notify_routes (
    id          BIGSERIAL PRIMARY KEY,
    level       SMALLINT NOT NULL,                    -- 1-5
    channel_ids BIGINT[] NOT NULL,                    -- 命中该级别走哪些渠道
    group_ids   BIGINT[] NOT NULL,                    -- 发给哪些接收组
    notify_on_recover BOOLEAN NOT NULL DEFAULT TRUE,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE notify_logs (
    id          BIGSERIAL PRIMARY KEY,
    alarm_id    BIGINT REFERENCES alarms(id),
    channel_id  BIGINT,
    recipient   VARCHAR(128),
    trigger     VARCHAR(16),                          -- raise|recover|digest
    status      VARCHAR(16) NOT NULL,                 -- sent|failed|retrying
    error       TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notify_logs_alarm ON notify_logs(alarm_id);

-- ========== 2.8 系统 ==========
CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,                      -- bcrypt
    role          VARCHAR(16) NOT NULL,               -- admin|operator|readonly
    display_name  VARCHAR(64),
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- EMS 连接配置（单条；敏感字段加密存储）
CREATE TABLE ems_config (
    id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    base_url        VARCHAR(255) NOT NULL,            -- http://EMS_IP:Port
    username        VARCHAR(64) NOT NULL,
    password_enc    TEXT NOT NULL,                    -- 加密
    recv_ip         VARCHAR(64) NOT NULL,             -- 本平台接收推送 ip
    recv_port       VARCHAR(8) NOT NULL,              -- 本平台接收推送 port
    version_str     VARCHAR(64) NOT NULL,             -- 协议 version 字段
    sync_interval_s INTEGER NOT NULL DEFAULT 21600,   -- 配置同步周期(默认6h)
    subscribe_data  BOOLEAN NOT NULL DEFAULT TRUE,
    subscribe_alarm BOOLEAN NOT NULL DEFAULT TRUE,
    deadband_enabled BOOLEAN NOT NULL DEFAULT FALSE,  -- 死区存储开关(默认关)
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE report_schedules (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(128),
    report_type VARCHAR(16) NOT NULL,                 -- alarm_daily|alarm_weekly|alarm_monthly
    cron        VARCHAR(64) NOT NULL,                 -- 定时表达式
    group_ids   BIGINT[] NOT NULL,                    -- 邮件接收组
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sync_log (
    id          BIGSERIAL PRIMARY KEY,
    kind        VARCHAR(16) NOT NULL,                 -- config|backfill
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    added       INTEGER DEFAULT 0,
    changed     INTEGER DEFAULT 0,
    inactivated INTEGER DEFAULT 0,
    detail      TEXT,
    success     BOOLEAN
);

CREATE TABLE system_settings (
    key   VARCHAR(64) PRIMARY KEY,
    value JSONB NOT NULL
);
```

---

## 3. Redis 键设计（最新值与实时）
| 键 | 类型 | 含义 | TTL |
|---|---|---|---|
| `rt:point:{point_id}` | Hash `{value, save_time}` | 测点最新值 | 滚动（如 10min，超时视为失联） |
| `rt:device:{device_id}` | String `0/1` | 设备最新通信状态 | 同上 |
| `ws:sub:{client}` | Set | WebSocket 客户端订阅的测点集 | 连接生命周期 |
| `ems:conn` | Hash `{state, last_heart, last_push, token_ok, reconnects}` | EMS 连接状态 | 实时更新 |
| `alarm:merge:{merge_key}` | String + TTL | 防轰炸合并窗口标记 | 合并窗口长度 |
| `lock:backfill` / `lock:history` | String(锁) | 历史/回补串行锁（遵守 EMS 单请求限制） | 任务期 |

> Pub/Sub：采集层收到推送写入最新值后，发布 `channel:realtime`，WebSocket 网关订阅后推送给前端。

---

## 4. 时间与单位约定
- 共济 `save_time / period / event_time` 等均为 **Unix 秒**；入库统一转 `TIMESTAMPTZ`（UTC 存储，按本地时区展示）。
- `real_value` 共济以字符串传输且要求数值型；落 `point_history.value` 前转 `double`，非数值（状态量映射）按 mapper 解释，必要时单独处理。
- 告警 `event_level` 字符串 "1"–"5"；落库统一为 `SMALLINT`。
