"""统一失败可观测：失败计数 + 最近失败时刻，写 Redis，供 /health 与告警暴露。

红线 #10.1：必须提供工具失败率指标、关键链路告警不得缺失。本模块负责把「被捕获的
失败」转化为可见信号（计数 + 最近时刻），替代「仅 logger.error 后继续」导致的静默失败。

约束：上报自身绝不能反向影响主流程——任何 Redis 异常在此被吞掉并降级为日志。
"""
from __future__ import annotations

import time

from app.core.constants import REDIS_METRICS_FAIL_COUNT, REDIS_METRICS_FAIL_TS
from app.core.logging import get_logger
from app.core.redis import redis_client

logger = get_logger("metrics")

# 失败指标名（稳定标识，供看板/告警按名聚合）
M_INGEST_PERSIST = "ingest_persist_failed"  # 实时落库失败（红线：数据不丢）
M_INGEST_REDIS = "ingest_redis_failed"  # 最新值/状态 Redis 写失败
M_INGEST_PARSE_DROP = "ingest_parse_drop"  # 脏数据（value/save_time 解析失败）丢弃计数
M_INGEST_PUSH_HANDLE = "ingest_push_handle_failed"  # 推送处理整体失败
M_RULE_EVAL = "rule_eval_failed"  # 规则评估失败（漏判风险）
M_ALARM_PUBLISH = "alarm_publish_failed"  # 告警事件发布失败（通知丢失风险）
M_ALARM_UNMATCHED = "alarm_unmatched"  # EMS 恢复/受理/确认未匹配到告警
M_BACKFILL_SLICE = "backfill_slice_failed"  # 回补分片失败（可能丢缺口）
M_NOTIFY_SEND = "notify_send_failed"  # 通知发送失败
M_NOTIFY_DECRYPT = "notify_decrypt_failed"  # 渠道凭据解密失败
M_EMS_OFFLINE = "ems_offline"  # EMS 连接进入离线
M_CONFIG_SYNC = "config_sync_failed"  # 定时配置同步失败
M_BACKFILL_WATCH = "backfill_watch_failed"  # 回补巡检自身失败


async def record_failure(name: str, *, error: str | None = None) -> None:
    """记录一次失败：计数 +1 并刷新最近失败时刻。自身异常被吞（不影响主流程）。"""
    try:
        ts = int(time.time())
        pipe = redis_client.pipeline()
        pipe.hincrby(REDIS_METRICS_FAIL_COUNT, name, 1)
        pipe.hset(REDIS_METRICS_FAIL_TS, name, ts)
        await pipe.execute()
        if error:
            logger.warning(
                "记录失败指标",
                extra={"extra_fields": {"metric": name, "error": error[:300]}},
            )
    except Exception as exc:  # 指标上报失败仅降级日志，绝不抛出
        logger.error(
            "记录失败指标自身失败",
            extra={"extra_fields": {"metric": name, "error": str(exc)}},
        )


async def get_failures() -> dict[str, dict[str, int]]:
    """读取全部失败指标 {name: {count, last_ts}}，供 /health 与报表暴露。"""
    try:
        counts = await redis_client.hgetall(REDIS_METRICS_FAIL_COUNT)
        timestamps = await redis_client.hgetall(REDIS_METRICS_FAIL_TS)
    except Exception:
        return {}
    out: dict[str, dict[str, int]] = {}
    for name, count in (counts or {}).items():
        try:
            out[str(name)] = {
                "count": int(count),
                "last_ts": int((timestamps or {}).get(name, 0) or 0),
            }
        except (TypeError, ValueError):
            continue
    return out
