"""跨模块共享常量（Shared Kernel）。

红线 #6.2：跨域通信仅允许通过公共 Shared Kernel / 事件总线 / 公共接口层。

封闭枚举域（告警状态/来源、连接状态、资源类型、EMS msg_type）以 StrEnum/IntEnum 表达，
schema 引用即可在 OpenAPI 输出 enum 约束、驱动前端类型（审查 S3/M1）。枚举「值」与历史字符串/
整数完全一致，故 JSON 契约不变；既有 `XXX_YYY` 常量名重定义为枚举成员以向后兼容、单一事实源。
"""
from __future__ import annotations

from enum import IntEnum, StrEnum

# Redis 键
REDIS_POINT_LATEST = "rt:point:{point_id}"  # Hash {value, save_time}
REDIS_DEVICE_STATUS = "rt:device:{device_id}"  # String 0/1
REDIS_EMS_CONN = "ems:conn"  # Hash {state,last_heart,last_push,token_ok,reconnects}

# 失败可观测指标（红线 #10.1）：name->累计次数 / name->最近失败 Unix 秒
REDIS_METRICS_FAIL_COUNT = "metrics:fail:count"
REDIS_METRICS_FAIL_TS = "metrics:fail:ts"

# 最新值滚动 TTL（秒）：超时视为失联
REDIS_LATEST_TTL = 600

# Pub/Sub 频道：采集层发布最新值，WebSocket 网关订阅（Sprint 2）
CHANNEL_REALTIME = "channel:realtime"

# EMS 连接状态
class ConnState(StrEnum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"


CONN_STATE_OFFLINE = ConnState.OFFLINE
CONN_STATE_CONNECTING = ConnState.CONNECTING
CONN_STATE_ONLINE = ConnState.ONLINE

# EMS 连续重连失败达到该次数 → 升级为 error 日志（采集疑似停摆，红线 #10.1）
EMS_SUSTAINED_OUTAGE_RECONNECTS = 3

# ---- 历史查询 / 断连回补（Sprint 2） ----
# 历史串行锁：红线 #5「同一时间仅一个历史请求在跑」。offline_value 调用统一经此锁。
REDIS_HISTORY_LOCK = "lock:history"
# 用户管理写操作互斥锁：串行化「保留至少一个管理员」守卫，防 TOCTOU 自锁（审查 C3）
REDIS_USER_ADMIN_LOCK = "lock:user_admin_guard"
# 配置同步互斥锁：首连/定时/手动同步并发时，避免基于过期快照交叉失活与统计不一致（审查 M5）
REDIS_CONFIG_SYNC_LOCK = "lock:config_sync"
REDIS_CONFIG_SYNC_LOCK_TTL = 600
# 写操作幂等键（红线 §18）：携带 Idempotency-Key 的写请求短窗口内去重，防重复副作用
REDIS_IDEMPOTENCY = "idem:{key}"
IDEMPOTENCY_TTL_S = 600
# 锁 TTL（秒）：防止异常未释放导致历史请求永久阻塞
REDIS_HISTORY_LOCK_TTL = 600

# 采集层写入的最新数据周期（Unix 秒），供回补巡检判定缺口边界
REDIS_INGEST_LAST_TS = "ingest:last_ts"
# 缺口开始时刻（Unix 秒）：检测到推送中断时冻结的最后有效数据时刻
REDIS_BACKFILL_GAP_START = "backfill:gap_start"

# 自动选层阈值：查询跨度 ≤ 此值（秒）走原始层，否则走 5min 降采样层
HISTORY_RAW_MAX_SPAN_S = 86400  # 1 天

# offline_value 接口硬限制（红线 #5）
OFFLINE_MAX_POINTS = 100  # 单次 ≤100 测点
OFFLINE_MAX_SPAN_S = 86400  # 单次跨度 ≤1 天

# 回补巡检：推送静默超过该秒数判定为中断（推送周期 10s，留足余量）
BACKFILL_GAP_THRESHOLD_S = 45
# 单次回补窗口跨度上限（秒）：防止 last_ts 长期不前进导致 gap_end 无界增长、分片爆炸
# 与历史锁中途过期（审查 B1/B2）。超出部分保留缺口待下轮续补。
BACKFILL_MAX_WINDOW_S = 7 * 86400  # 最多回补最近 7 天
# 回补使用的降采样粒度（与 5min 连续聚合对齐）
BACKFILL_INTERVAL = "five"
# 实时落库失败时缺口起点的回退步长（秒）：当无更早的有效时刻可用时，缺口起点取
# period - 该值，保证 gap_end(=period) > gap_start，使 backfill_watch 不把缺口当空窗口删除
# （审查 S2）。对齐实时推送周期（10s）。
REALTIME_FALLBACK_GAP_S = 10

# ---- 规则引擎 / 告警生命周期 / 抑制（Sprint 3） ----
# 去抖：规则首次越限时刻（Unix 秒）；持续 ≥ continuous_time 才产生告警
REDIS_RULE_BREACH = "rule:breach:{rule_id}"
# 恢复保持：规则首次满足恢复条件时刻；保持 ≥ recover_hold_time 才自动恢复
REDIS_RULE_RECOVER = "rule:recover:{rule_id}"
# 去抖/恢复计时键 TTL（秒）：兜底清理陈旧计时
RULE_TIMER_TTL = 3600

# 防轰炸合并窗口标记（开发约定「防轰炸/去抖/恢复」：同点高频告警合并；非红线 #7）
REDIS_ALARM_MERGE = "alarm:merge:{merge_key}"
# 默认合并窗口（秒）：窗口内同 merge_key 的再次触发合并计数而非新建/再通知
ANTI_FLOOD_MERGE_WINDOW_S = 300

# 资源类型（ci_type）
class ResourceKind(IntEnum):
    SPACE = 5
    DEVICE = 2
    POINT = 3


RESOURCE_KIND_SPACE = ResourceKind.SPACE
RESOURCE_KIND_DEVICE = ResourceKind.DEVICE
RESOURCE_KIND_POINT = ResourceKind.POINT


# 告警来源
class AlarmSource(StrEnum):
    PLATFORM = "platform"
    EMS = "ems"


ALARM_SOURCE_PLATFORM = AlarmSource.PLATFORM
ALARM_SOURCE_EMS = AlarmSource.EMS


# 告警状态机
class AlarmStatus(StrEnum):
    ACTIVE = "active"
    ACCEPTED = "accepted"
    CONFIRMED = "confirmed"
    RECOVERED = "recovered"


ALARM_STATUS_ACTIVE = AlarmStatus.ACTIVE
ALARM_STATUS_ACCEPTED = AlarmStatus.ACCEPTED
ALARM_STATUS_CONFIRMED = AlarmStatus.CONFIRMED
ALARM_STATUS_RECOVERED = AlarmStatus.RECOVERED

# EMS 告警纳入的 event_type（红线 #7：仅通信中断/故障/停止采集，其余阈值类丢弃去重）
EMS_ALARM_ACCEPT_TYPES: frozenset[int] = frozenset({0, 21, 30})


# EMS 告警推送 msg_type 语义
class EmsMsgType(IntEnum):
    RAISE = 0
    RECOVER = 1
    ACCEPT = 2
    CONFIRM = 3


EMS_MSG_RAISE = EmsMsgType.RAISE
EMS_MSG_RECOVER = EmsMsgType.RECOVER
EMS_MSG_ACCEPT = EmsMsgType.ACCEPT
EMS_MSG_CONFIRM = EmsMsgType.CONFIRM

# ---- 通知（Sprint 4） ----
# 告警生命周期事件总线：lifecycle 发布，notify worker 订阅（红线 #6.2 事件总线）
CHANNEL_ALARM_EVENTS = "channel:alarm_events"

# 通知触发类型
NOTIFY_TRIGGER_RAISE = "raise"
NOTIFY_TRIGGER_RECOVER = "recover"
NOTIFY_TRIGGER_DIGEST = "digest"

# 防轰炸摘要：合并期内累积计数 Hash，field=merge_key value=累计次数
REDIS_NOTIFY_DIGEST = "notify:digest"
# 摘要附带信息 Hash：field=merge_key value=JSON{level,resource_id,content}
REDIS_NOTIFY_DIGEST_META = "notify:digest:meta"
# 告警事件发布失败补偿队列（List）：已 commit 但 Pub/Sub 发布失败的事件入队，由调度器重投，
# 避免「告警已落库但通知永久丢失」（审查 M2）。超过最大尝试次数后丢弃并记指标。
REDIS_NOTIFY_PENDING = "notify:pending_events"
NOTIFY_PENDING_MAX_ATTEMPTS = 5
# 重投巡检间隔（秒）
NOTIFY_RETRY_INTERVAL_S = 60

# 通知发送幂等键（审查 I1）：发送前 SETNX 预留，避免重投/重复消费导致重复外呼（§18/§19）
REDIS_NOTIFY_DEDUP = "notify:dedup:{alarm_id}:{channel_id}:{recipient}:{trigger}"
# 幂等键 TTL（秒）：略大于合并窗口，覆盖一轮重投周期
NOTIFY_DEDUP_TTL_S = ANTI_FLOOD_MERGE_WINDOW_S + NOTIFY_RETRY_INTERVAL_S
# 摘要累计 Hash 兜底 TTL（秒）：> flush 周期，flush 停摆时防 Redis 泄漏与明文滞留（审查 I3）
NOTIFY_DIGEST_HASH_TTL_S = ANTI_FLOOD_MERGE_WINDOW_S * 4

# 发送重试次数（首发之外的额外重试）与间隔（秒）
NOTIFY_MAX_RETRY = 2
NOTIFY_RETRY_BACKOFF_S = 1.0
# 外呼/HTTP 渠道超时（秒）：红线 #20 显式区分连接/读取超时
NOTIFY_HTTP_TIMEOUT_S = 8.0  # 兼容保留（总超时语义）
NOTIFY_HTTP_CONNECT_S = 5.0
NOTIFY_HTTP_READ_S = 8.0
# 周期摘要刷新间隔（秒）：与合并窗口对齐
NOTIFY_DIGEST_INTERVAL_S = ANTI_FLOOD_MERGE_WINDOW_S

# 渠道 config 中需加密存储/读取脱敏的敏感字段
CHANNEL_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {"secret", "api_key", "app_secret", "password", "token", "access_token", "smtp_password"}
)
CHANNEL_SECRET_MASK = "********"
