"""告警/规则封闭域 CHECK 约束（审查 M4）

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-21

让 DB 成为状态/来源/操作符等封闭域的最后防线，拦截绕过 Pydantic 的非法写入（迁移/回补/
内部 service 直接构造）。仅约束平台完全可控的字段：

- alarm_rules.operator / restore_operator ∈ {> < = <> <= >=}（restore 允许 NULL）
- alarm_rules.cond_type ∈ {threshold, range}
- alarms.source ∈ {platform, ems}
- alarms.status ∈ {active, accepted, confirmed, recovered}
- alarms.resource_kind ∈ {2(设备), 3(测点), 5(空间)}

device_status.status 来源于 EMS（外部、取值不完全可控），不加 CHECK 以免非常规状态码阻断
实时落库（宁可记录也不丢数据）。

回滚路径：downgrade 逐个 drop_constraint，不影响数据。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPERATORS = "'>', '<', '=', '<>', '<=', '>='"

_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    ("alarm_rules", "ck_alarm_rules_operator", f"operator IN ({_OPERATORS})"),
    (
        "alarm_rules",
        "ck_alarm_rules_restore_operator",
        f"restore_operator IS NULL OR restore_operator IN ({_OPERATORS})",
    ),
    ("alarm_rules", "ck_alarm_rules_cond_type", "cond_type IN ('threshold', 'range')"),
    ("alarms", "ck_alarms_source", "source IN ('platform', 'ems')"),
    (
        "alarms",
        "ck_alarms_status",
        "status IN ('active', 'accepted', 'confirmed', 'recovered')",
    ),
    ("alarms", "ck_alarms_resource_kind", "resource_kind IN (2, 3, 5)"),
)


def upgrade() -> None:
    for table, name, condition in _CONSTRAINTS:
        op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    for table, name, _condition in reversed(_CONSTRAINTS):
        op.drop_constraint(name, table, type_="check")
