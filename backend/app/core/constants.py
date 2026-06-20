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
# 回补使用的降采样粒度（与 5min 连续聚合对齐）
BACKFILL_INTERVAL = "five"

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

# 发送重试次数（首发之外的额外重试）与间隔（秒）
NOTIFY_MAX_RETRY = 2
NOTIFY_RETRY_BACKOFF_S = 1.0
# 外呼/HTTP 渠道超时（秒）
NOTIFY_HTTP_TIMEOUT_S = 8.0
# 周期摘要刷新间隔（秒）：与合并窗口对齐
NOTIFY_DIGEST_INTERVAL_S = ANTI_FLOOD_MERGE_WINDOW_S

# 渠道 config 中需加密存储/读取脱敏的敏感字段
CHANNEL_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {"secret", "api_key", "app_secret", "password", "token", "access_token", "smtp_password"}
)
CHANNEL_SECRET_MASK = "********"
