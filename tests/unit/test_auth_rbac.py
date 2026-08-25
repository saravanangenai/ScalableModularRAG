import pytest

from packages.auth.rbac import tenant_role_at_least, workspace_role_at_least


@pytest.mark.parametrize(
    "actual,minimum,expected",
    [
        ("owner", "member", True),
        ("owner", "admin", True),
        ("owner", "owner", True),
        ("admin", "member", True),
        ("admin", "admin", True),
        ("admin", "owner", False),
        ("member", "member", True),
        ("member", "admin", False),
        ("member", "owner", False),
    ],
)
def test_tenant_role_at_least(actual, minimum, expected):
    assert tenant_role_at_least(actual, minimum) is expected


@pytest.mark.parametrize(
    "actual,minimum,expected",
    [
        ("owner", "viewer", True),
        ("owner", "editor", True),
        ("owner", "owner", True),
        ("editor", "viewer", True),
        ("editor", "editor", True),
        ("editor", "owner", False),
        ("viewer", "viewer", True),
        ("viewer", "editor", False),
        ("viewer", "owner", False),
    ],
)
def test_workspace_role_at_least(actual, minimum, expected):
    assert workspace_role_at_least(actual, minimum) is expected
