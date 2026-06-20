"""断连回补分批/分片单元测试（离线、确定性）。

强校验红线 #5：offline_value 单次 ≤100 测点、单次跨度 ≤1 天。
"""
from app.core.constants import OFFLINE_MAX_POINTS, OFFLINE_MAX_SPAN_S
from app.history.backfill import chunk_points, slice_time_range


def test_chunk_points_respects_max_100() -> None:
    ids = [f"p{i}" for i in range(250)]
    batches = chunk_points(ids)
    assert all(len(b) <= OFFLINE_MAX_POINTS for b in batches)
    assert sum(len(b) for b in batches) == 250
    # 顺序保持、无丢失
    assert [i for b in batches for i in b] == ids


def test_chunk_points_dedup_preserves_order() -> None:
    ids = ["a", "b", "a", "c", "b"]
    assert chunk_points(ids) == [["a", "b", "c"]]


def test_chunk_points_empty() -> None:
    assert chunk_points([]) == []
    assert chunk_points(["", "", "x"]) == [["x"]]


def test_slice_time_range_respects_max_1_day() -> None:
    start = 1_700_000_000
    end = start + 3 * OFFLINE_MAX_SPAN_S + 500  # 3 天多一点
    slices = slice_time_range(start, end)
    assert all((e - s) <= OFFLINE_MAX_SPAN_S for s, e in slices)
    # 连续覆盖且不留缝隙
    assert slices[0][0] == start
    assert slices[-1][1] == end
    for (_s1, e1), (s2, _e2) in zip(slices, slices[1:], strict=False):
        assert e1 == s2


def test_slice_time_range_within_one_day_single_slice() -> None:
    start = 1_700_000_000
    slices = slice_time_range(start, start + 3600)
    assert slices == [(start, start + 3600)]


def test_slice_time_range_invalid() -> None:
    assert slice_time_range(100, 100) == []
    assert slice_time_range(200, 100) == []
