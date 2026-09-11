import pytest

from packages.auth.rbac import workspace_role_at_least


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
