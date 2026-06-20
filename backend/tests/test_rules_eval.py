"""规则引擎纯函数单元测试（离线、确定性）。"""
import dataclasses

from app.engine.rules import (
    RuleSpec,
    compare,
    eval_condition,
    eval_restore,
    highest,
    platform_event_type,
)

_BASE = RuleSpec(
    id=1, point_id="p", level=3, priority=0, operator=">", operand=30.0,
    operand_min=None, operand_max=None, cond_type="threshold",
    restore_operator=None, restore_operand=None,
    continuous_time=0, recover_hold_time=0, content_tpl=None, suggest=None,
)


def _spec(**kw: object) -> RuleSpec:
    return dataclasses.replace(_BASE, **kw)


def test_compare_operators() -> None:
    assert compare(31, ">", 30) is True
    assert compare(30, ">", 30) is False
    assert compare(29, "<", 30) is True
    assert compare(30, ">=", 30) is True
    assert compare(30, "<=", 30) is True
    assert compare(30, "=", 30) is True
    assert compare(31, "<>", 30) is True
    assert compare(30, "<>", 30) is False
    assert compare(5, ">", None) is False  # operand 缺失


def test_eval_condition_threshold_and_range() -> None:
    assert eval_condition(35, _spec(operator=">", operand=30)) is True
    assert eval_condition(25, _spec(operator=">", operand=30)) is False
    # 区间：min ≤ value ≤ max 命中
    r = _spec(cond_type="range", operand=None, operand_min=10, operand_max=20)
    assert eval_condition(15, r) is True
    assert eval_condition(20, r) is True
    assert eval_condition(21, r) is False


def test_eval_restore_default_and_explicit() -> None:
    # 默认：不再满足触发条件即恢复
    spec = _spec(operator=">", operand=30)
    assert eval_restore(25, spec) is True
    assert eval_restore(35, spec) is False
    # 显式恢复条件（带回差）：value < 28 才恢复
    spec2 = _spec(operator=">", operand=30, restore_operator="<", restore_operand=28)
    assert eval_restore(29, spec2) is False  # 仍在回差区
    assert eval_restore(27, spec2) is True


def test_highest_picks_most_severe() -> None:
    warn = _spec(id=1, level=4, priority=0)
    crit = _spec(id=2, level=1, priority=0)
    mid = _spec(id=3, level=3, priority=0)
    top = highest([warn, crit, mid])
    assert top is not None and top.id == 2
    # 同级取 priority 大者
    a = _spec(id=10, level=2, priority=1)
    b = _spec(id=11, level=2, priority=5)
    top2 = highest([a, b])
    assert top2 is not None and top2.id == 11
    assert highest([]) is None


def test_platform_event_type_mapping() -> None:
    assert platform_event_type(">") == 2  # 过高
    assert platform_event_type(">=") == 2
    assert platform_event_type("<") == 4  # 过低
    assert platform_event_type("<=") == 4
    assert platform_event_type("=") == 3  # 不正常
    assert platform_event_type("<>") == 3
