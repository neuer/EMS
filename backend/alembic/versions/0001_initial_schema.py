"""初始 schema：落 02 数据模型全部 DDL（含 TimescaleDB hypertable / 连续聚合 / 压缩 / 保留策略）

Revision ID: 0001
Revises:
Create Date: 2026-06-17

回滚路径：downgrade 删除连续聚合与全部表（CASCADE），扩展保留不动。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---- 扩展 ----
EXTENSIONS = """
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
"""

# ---- 2.1 EMS 同步对象 ----
SYNC_OBJECTS = """
CREATE TABLE spaces (
    resource_id   VARCHAR(64) PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    parent_id     VARCHAR(64),
    location      TEXT,
    space_type    SMALLINT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_spaces_parent ON spaces(parent_id);

CREATE TABLE devices (
    resource_id   VARCHAR(64) PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    device_type   VARCHAR(64),
    parent_id     VARCHAR(64),
    location      TEXT,
    link          TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_devices_parent ON devices(parent_id);

CREATE TABLE points (
    resource_id     VARCHAR(64) PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    device_id       VARCHAR(64) NOT NULL,
    spot_type       SMALLINT,
    unit            VARCHAR(64),
    mapper          TEXT,
    access          VARCHAR(8),
    raw_filter      TEXT,
    raw_event_rules TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_points_device ON points(device_id);
"""

# ---- 2.2 元数据增强 ----
ASSET_META = """
CREATE TABLE asset_meta (
    resource_id   VARCHAR(64) PRIMARY KEY,
    asset_kind    SMALLINT NOT NULL,
    alias         VARCHAR(128),
    group_name    VARCHAR(128),
    tags          TEXT[],
    importance    SMALLINT,
    custom_unit   VARCHAR(64),
    remark        TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_meta_group ON asset_meta(group_name);
CREATE INDEX idx_meta_tags ON asset_meta USING GIN(tags);
"""

# ---- 2.3 时序数据：原始层（30 天）+ 压缩 + 保留 ----
TIME_SERIES_RAW = """
CREATE TABLE point_history (
    point_id    VARCHAR(64) NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    value       DOUBLE PRECISION,
    PRIMARY KEY (point_id, ts)
);
SELECT create_hypertable('point_history', 'ts', chunk_time_interval => INTERVAL '1 day');

ALTER TABLE point_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'point_id',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('point_history', INTERVAL '7 days');
SELECT add_retention_policy('point_history', INTERVAL '30 days');
"""

# ---- 2.3 降采样层：5min 连续聚合（6 个月）----
# 注意：连续聚合不可在事务块内创建，env.py 已配置 AUTOCOMMIT。
TIME_SERIES_CAGG = """
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
"""

TIME_SERIES_CAGG_POLICY = """
SELECT add_continuous_aggregate_policy('point_history_5min',
    start_offset => INTERVAL '1 day',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes');
SELECT add_retention_policy('point_history_5min', INTERVAL '180 days');
"""

DEVICE_STATUS = """
CREATE TABLE device_status (
    device_id   VARCHAR(64) PRIMARY KEY,
    status      SMALLINT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# ---- 2.4 预警规则 ----
ALARM_RULES = """
CREATE TABLE alarm_rules (
    id                BIGSERIAL PRIMARY KEY,
    point_id          VARCHAR(64) NOT NULL REFERENCES points(resource_id),
    name              VARCHAR(128),
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    operator          VARCHAR(4) NOT NULL,
    operand           DOUBLE PRECISION,
    operand_min       DOUBLE PRECISION,
    operand_max       DOUBLE PRECISION,
    cond_type         VARCHAR(16) NOT NULL DEFAULT 'threshold',
    restore_operator  VARCHAR(4),
    restore_operand   DOUBLE PRECISION,
    continuous_time   INTEGER NOT NULL DEFAULT 0,
    recover_hold_time INTEGER NOT NULL DEFAULT 0,
    level             SMALLINT NOT NULL,
    priority          SMALLINT NOT NULL DEFAULT 0,
    content_tpl       TEXT,
    suggest           TEXT,
    created_by        BIGINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rules_point ON alarm_rules(point_id) WHERE enabled;
"""

# ---- 2.5 告警 ----
ALARMS = """
CREATE TABLE alarms (
    id              BIGSERIAL PRIMARY KEY,
    source          VARCHAR(16) NOT NULL,
    guid            VARCHAR(80),
    rule_id         BIGINT REFERENCES alarm_rules(id),
    resource_id     VARCHAR(64) NOT NULL,
    resource_kind   SMALLINT NOT NULL,
    event_type      SMALLINT,
    level           SMALLINT NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    trigger_value   DOUBLE PRECISION,
    content         TEXT,
    suggest         TEXT,
    masked          BOOLEAN NOT NULL DEFAULT FALSE,
    silenced_reason VARCHAR(32),
    merge_key       VARCHAR(160),
    merge_count     INTEGER NOT NULL DEFAULT 1,
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

CREATE TABLE alarm_events (
    id          BIGSERIAL PRIMARY KEY,
    alarm_id    BIGINT NOT NULL REFERENCES alarms(id) ON DELETE CASCADE,
    event       VARCHAR(16) NOT NULL,
    operator_id BIGINT,
    note        TEXT,
    snapshot    DOUBLE PRECISION,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alarm_events_alarm ON alarm_events(alarm_id, occurred_at);
"""

# ---- 2.6 抑制 ----
SUPPRESS = """
CREATE TABLE point_mute (
    id          BIGSERIAL PRIMARY KEY,
    point_id    VARCHAR(64) NOT NULL,
    reason      TEXT,
    start_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    end_at      TIMESTAMPTZ,
    created_by  BIGINT,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_mute_point ON point_mute(point_id) WHERE enabled;

CREATE TABLE maintenance_windows (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(128),
    scope_kind      SMALLINT NOT NULL,
    scope_ids       TEXT[] NOT NULL,
    start_at        TIMESTAMPTZ NOT NULL,
    end_at          TIMESTAMPTZ NOT NULL,
    record_silenced BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_maint_time ON maintenance_windows(start_at, end_at);
"""

# ---- 2.7 通知 ----
NOTIFY = """
CREATE TABLE notify_channels (
    id          BIGSERIAL PRIMARY KEY,
    type        VARCHAR(16) NOT NULL,
    name        VARCHAR(64) NOT NULL,
    config      JSONB NOT NULL,
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

CREATE TABLE notify_routes (
    id                BIGSERIAL PRIMARY KEY,
    level             SMALLINT NOT NULL,
    channel_ids       BIGINT[] NOT NULL,
    group_ids         BIGINT[] NOT NULL,
    notify_on_recover BOOLEAN NOT NULL DEFAULT TRUE,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE notify_logs (
    id          BIGSERIAL PRIMARY KEY,
    alarm_id    BIGINT REFERENCES alarms(id),
    channel_id  BIGINT,
    recipient   VARCHAR(128),
    trigger     VARCHAR(16),
    status      VARCHAR(16) NOT NULL,
    error       TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notify_logs_alarm ON notify_logs(alarm_id);
"""

# ---- 2.8 系统 ----
SYSTEM = """
CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          VARCHAR(16) NOT NULL,
    display_name  VARCHAR(64),
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ems_config (
    id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    base_url         VARCHAR(255) NOT NULL,
    username         VARCHAR(64) NOT NULL,
    password_enc     TEXT NOT NULL,
    recv_ip          VARCHAR(64) NOT NULL,
    recv_port        VARCHAR(8) NOT NULL,
    version_str      VARCHAR(64) NOT NULL,
    sync_interval_s  INTEGER NOT NULL DEFAULT 21600,
    subscribe_data   BOOLEAN NOT NULL DEFAULT TRUE,
    subscribe_alarm  BOOLEAN NOT NULL DEFAULT TRUE,
    deadband_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE report_schedules (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(128),
    report_type VARCHAR(16) NOT NULL,
    cron        VARCHAR(64) NOT NULL,
    group_ids   BIGINT[] NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sync_log (
    id          BIGSERIAL PRIMARY KEY,
    kind        VARCHAR(16) NOT NULL,
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
"""


def _exec(sql: str) -> None:
    op.execute(sql)


def upgrade() -> None:
    _exec(EXTENSIONS)
    _exec(SYNC_OBJECTS)
    _exec(ASSET_META)
    _exec(TIME_SERIES_RAW)
    _exec(TIME_SERIES_CAGG)
    _exec(TIME_SERIES_CAGG_POLICY)
    _exec(DEVICE_STATUS)
    _exec(ALARM_RULES)
    _exec(ALARMS)
    _exec(SUPPRESS)
    _exec(NOTIFY)
    _exec(SYSTEM)


def downgrade() -> None:
    # 连续聚合先删；其余表 CASCADE 删除。扩展保留。
    _exec("DROP MATERIALIZED VIEW IF EXISTS point_history_5min CASCADE;")
    for table in [
        "system_settings",
        "sync_log",
        "report_schedules",
        "ems_config",
        "users",
        "notify_logs",
        "notify_routes",
        "recipient_group_members",
        "recipient_groups",
        "recipients",
        "notify_channels",
        "maintenance_windows",
        "point_mute",
        "alarm_events",
        "alarms",
        "alarm_rules",
        "device_status",
        "point_history",
        "asset_meta",
        "points",
        "devices",
        "spaces",
    ]:
        _exec(f"DROP TABLE IF EXISTS {table} CASCADE;")
