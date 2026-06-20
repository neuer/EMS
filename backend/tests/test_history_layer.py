"""历史分层选层单元测试（离线、确定性）。"""
from app.core.constants import HISTORY_RAW_MAX_SPAN_S
from app.history.query import select_layer


def test_explicit_layer_wins() -> None:
    # 显式 raw/5min 直接采用，忽略跨度
    assert select_layer(0, 10 * HISTORY_RAW_MAX_SPAN_S, "raw") == "raw"
    assert select_layer(0, 60, "5min") == "5min"


def test_auto_short_range_hits_raw() -> None:
    # 跨度 ≤ 阈值 → 原始层
    assert select_layer(1000, 1000 + HISTORY_RAW_MAX_SPAN_S, "auto") == "raw"
    assert select_layer(1000, 1000 + 3600, "auto") == "raw"


def test_auto_long_range_hits_5min() -> None:
    # 跨度 > 阈值 → 降采样层
    assert select_layer(0, HISTORY_RAW_MAX_SPAN_S + 1, "auto") == "5min"
    assert select_layer(0, 7 * HISTORY_RAW_MAX_SPAN_S, "auto") == "5min"
