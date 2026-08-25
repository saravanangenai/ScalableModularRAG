_TENANT_ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}
_WORKSPACE_ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}


def tenant_role_at_least(actual_role: str, minimum_role: str) -> bool:
    return _TENANT_ROLE_RANK[actual_role] >= _TENANT_ROLE_RANK[minimum_role]


def workspace_role_at_least(actual_role: str, minimum_role: str) -> bool:
    return _WORKSPACE_ROLE_RANK[actual_role] >= _WORKSPACE_ROLE_RANK[minimum_role]
