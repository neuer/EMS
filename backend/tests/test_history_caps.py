"""历史查询上限测试（审查 I3）。防百测点×数月原始行拖垮 DB。"""
from __future__ import annotations

import pytest
from app.core.constants import HISTORY_RAW_MAX_SPAN_S, OFFLINE_MAX_POINTS
from app.schemas.history import HistoryQuery
from pydantic import ValidationError


def test_point_ids_capped():
    too_many = [f"p{i}" for i in range(OFFLINE_MAX_POINTS + 1)]
    with pytest.raises(ValidationError):
        HistoryQuery(point_ids=too_many, start=0, end=100, agg="auto")


def test_raw_span_capped():
    with pytest.raises(ValidationError):
        HistoryQuery(point_ids=["p1"], start=0, end=HISTORY_RAW_MAX_SPAN_S + 10, agg="raw")


def test_auto_large_span_allowed():
    # auto 大跨度合法（会自动落 5min 层）
    q = HistoryQuery(point_ids=["p1"], start=0, end=HISTORY_RAW_MAX_SPAN_S * 30, agg="auto")
    assert q.agg == "auto"


def test_end_must_exceed_start():
    with pytest.raises(ValidationError):
        HistoryQuery(point_ids=["p1"], start=100, end=100, agg="auto")
