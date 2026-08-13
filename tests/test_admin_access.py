import pytest

from foxgen.admin.errors import AdminAuthorizationError
from foxgen.admin.policy import ADMIN_MANAGE, ALL_SCOPES, ROLE_SCOPES, AdminContext


def test_only_superadmin_role_gets_admin_manage_by_default() -> None:
    assert ADMIN_MANAGE in ROLE_SCOPES["superadmin"]
    for role, scopes in ROLE_SCOPES.items():
        if role != "superadmin":
            assert ADMIN_MANAGE not in scopes


def test_regular_operator_cannot_manage_admins() -> None:
    context = AdminContext(
        user_id=10,
        role="operator",
        scopes=ROLE_SCOPES["operator"],
        request_id="req",
    )
    with pytest.raises(AdminAuthorizationError):
        context.require(ADMIN_MANAGE)


def test_superadmin_can_manage_admins() -> None:
    context = AdminContext(
        user_id=1,
        role="superadmin",
        scopes=ALL_SCOPES,
        request_id="req",
    )
    context.require(ADMIN_MANAGE)
