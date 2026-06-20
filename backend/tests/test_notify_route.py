"""通知路由/文案纯函数单元测试（离线、确定性）。"""
from types import SimpleNamespace

from app.notify.dispatcher import digest_text, render_subject, route_for_level


def _route(level: int, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(level=level, enabled=enabled)


def test_route_for_level_picks_enabled_match() -> None:
    routes = [_route(4), _route(2), _route(1, enabled=False)]
    r2 = route_for_level(routes, 2)
    r4 = route_for_level(routes, 4)
    assert r2 is not None and r2.level == 2
    assert r4 is not None and r4.level == 4


def test_route_for_level_skips_disabled_and_missing() -> None:
    routes = [_route(1, enabled=False), _route(3)]
    assert route_for_level(routes, 1) is None  # 该级别仅有禁用路由
    assert route_for_level(routes, 5) is None  # 无该级别
    assert route_for_level([], 2) is None


def test_render_subject() -> None:
    assert render_subject(1, "raise", "d_x") == "[紧急告警] d_x"
    assert render_subject(2, "recover", "d_y") == "[严重恢复] d_y"
    assert render_subject(3, "digest", "d_z") == "[重要告警摘要] d_z"


def test_digest_text_contains_count() -> None:
    txt = digest_text("d_x", 2, 5, "温度过高")
    assert "5 次" in txt
    assert "严重告警摘要" in txt
    assert "温度过高" in txt
