"""配置同步字段映射单元测试（离线、确定性）。"""
from app.sync.config_sync import _map_device, _map_point, _map_space, _to_int


def test_to_int() -> None:
    assert _to_int("5") == 5
    assert _to_int(3) == 3
    assert _to_int("") is None
    assert _to_int(None) is None
    assert _to_int("x") is None


def test_map_space() -> None:
    raw = {
        "resource_id": "0_root",
        "name": "厦门数据中心",
        "parent_id": "",
        "location": "project_root/",
        "space_type": "1",
    }
    out = _map_space(raw)
    assert out["resource_id"] == "0_root"
    assert out["parent_id"] is None  # 空串归一为 None
    assert out["space_type"] == 1


def test_map_device() -> None:
    raw = {
        "resource_id": "d_ups1",
        "name": "1#UPS",
        "device_type": "UPS设备",
        "parent_id": "0_room1",
    }
    out = _map_device(raw)
    assert out["resource_id"] == "d_ups1"
    assert out["parent_id"] == "0_room1"


def test_map_point() -> None:
    raw = {
        "resource_id": "d_ups1_p_outv",
        "name": "UPS输出电压",
        "spot_type": "1",
        "unit": "V",
        "mapper": "",
        "access": "r",
        "event_rules": ["id=1;operator=>;operand=245"],
        "filter": "filter=DefFilter;max=10000",
    }
    out = _map_point(raw, "d_ups1")
    assert out["device_id"] == "d_ups1"
    assert out["spot_type"] == 1
    assert out["raw_filter"] == "filter=DefFilter;max=10000"
    assert "operand=245" in out["raw_event_rules"]
