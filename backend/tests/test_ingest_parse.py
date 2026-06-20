"""实时采集解析工具单元测试（离线、确定性）。"""
from datetime import UTC

from app.ingest.realtime import _to_float, _to_utc


def test_to_float() -> None:
    assert _to_float("222.2") == 222.2
    assert _to_float(18) == 18.0
    assert _to_float("") is None
    assert _to_float(None) is None
    assert _to_float("abc") is None


def test_to_utc() -> None:
    dt = _to_utc(1468471315)
    assert dt is not None
    assert dt.tzinfo == UTC
    assert dt.year == 2016
    # 字符串数字也可解析
    assert _to_utc("1468471315") is not None
    assert _to_utc("bad") is None
