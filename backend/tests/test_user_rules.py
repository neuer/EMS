"""用户管理不变量守卫单元测试（离线、确定性）。

覆盖红线：管理员账户不可被删除/降级/禁用到「零启用管理员」。
"""
from app.api.users import will_keep_an_admin
from app.core.security import Role


def test_delete_one_of_many_admins_ok() -> None:
    admins = {"admin", "ops_admin"}
    assert will_keep_an_admin(admins, "admin", delete=True) is True


def test_delete_last_admin_blocked() -> None:
    admins = {"admin"}
    assert will_keep_an_admin(admins, "admin", delete=True) is False


def test_demote_last_admin_blocked() -> None:
    admins = {"admin"}
    assert will_keep_an_admin(admins, "admin", new_role=Role.OPERATOR) is False


def test_disable_last_admin_blocked() -> None:
    admins = {"admin"}
    assert will_keep_an_admin(admins, "admin", new_enabled=False) is False


def test_keep_admin_role_unchanged_ok() -> None:
    admins = {"admin"}
    # 仅改 display_name（role/enabled 未变）仍保留管理员
    assert will_keep_an_admin(admins, "admin", new_role=None, new_enabled=None) is True


def test_demote_one_of_many_admins_ok() -> None:
    admins = {"admin", "ops_admin"}
    assert will_keep_an_admin(admins, "ops_admin", new_role=Role.READONLY) is True


def test_reenable_admin_explicit_true_ok() -> None:
    admins = {"admin"}
    # 显式置 enabled=True 不应被判定为失去管理资格
    assert will_keep_an_admin(admins, "admin", new_role=Role.ADMIN, new_enabled=True) is True
