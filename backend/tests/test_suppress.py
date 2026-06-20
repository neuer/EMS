"""抑制纯函数单元测试（离线、确定性）。"""
from datetime import UTC, datetime, timedelta

from app.engine.suppress import build_merge_key, within_window


def test_within_window_bounds() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    start = now - timedelta(hours=1)
    end = now + timedelta(hours=1)
    assert within_window(start, end, now) is True
    assert within_window(now + timedelta(minutes=1), end, now) is False  # 未到开始
    assert within_window(start, now - timedelta(minutes=1), now) is False  # 已过结束


def test_within_window_open_ended() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    # end 为 None：长期有效
    assert within_window(now - timedelta(days=1), None, now) is True
    # start 为 None：无下界
    assert within_window(None, now + timedelta(days=1), now) is True


def test_build_merge_key() -> None:
    assert build_merge_key("platform", 7, "p1") == "platform:7:p1"
    assert build_merge_key("ems", 0, "dev1") == "ems:0:dev1"
