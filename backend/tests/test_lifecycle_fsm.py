"""告警生命周期状态机纯函数单元测试（离线、确定性）。"""
import pytest
from app.engine.lifecycle import next_status


def test_accept_transitions() -> None:
    assert next_status("active", "accept") == "accepted"
    assert next_status("accepted", "accept") == "accepted"  # 幂等


def test_confirm_transitions() -> None:
    assert next_status("active", "confirm") == "confirmed"  # 可直达确认
    assert next_status("accepted", "confirm") == "confirmed"
    assert next_status("confirmed", "confirm") == "confirmed"


def test_illegal_transitions_raise() -> None:
    with pytest.raises(ValueError):
        next_status("recovered", "accept")
    with pytest.raises(ValueError):
        next_status("recovered", "confirm")
    with pytest.raises(ValueError):
        next_status("active", "unknown")
