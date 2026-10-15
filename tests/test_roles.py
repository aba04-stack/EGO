"""Tests for access roles and the guest read-only policy."""
from __future__ import annotations

import pytest

from alterego_training_hub.roles import (
    AccessDenied,
    RolePolicy,
    can,
    normalize_role,
    require,
    role_id_by_label,
    role_ids,
    role_labels,
)


def test_roles_and_permissions():
    assert set(role_ids()) == {"owner", "editor", "viewer"}
    assert len(role_labels()) == 3
    assert role_id_by_label("Гость — только чтение") == "viewer"
    assert role_id_by_label("что-то") == "owner"  # fallback

    assert can("owner", "manage_secrets")
    assert can("editor", "mutate") and not can("editor", "manage_secrets")
    assert can("viewer", "read") and not can("viewer", "write")
    assert not can("viewer", "mutate") and not can("viewer", "run")
    assert can("НЕИЗВЕСТНО", "read")  # unknown → owner default


def test_normalize_and_require():
    assert normalize_role("Viewer") == "viewer"
    assert normalize_role("") == "owner"
    require("owner", "manage_roles")
    with pytest.raises(AccessDenied):
        require("viewer", "mutate", "запуск обучения")


def test_role_policy_flags():
    assert not RolePolicy("owner").readonly
    assert not RolePolicy("editor").agent_readonly
    policy = RolePolicy("viewer")
    assert policy.readonly and policy.agent_readonly
    assert policy.can("read") and not policy.can("write")
