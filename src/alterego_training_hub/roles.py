"""Access roles: owner / editor / viewer (guest) with explicit permissions.

Pure policy — the UI and the agent consult ``can()`` before any mutation.
The guest role turns every tool read-only without touching stored data.
"""
from __future__ import annotations

from dataclasses import dataclass

PERMISSIONS: dict[str, frozenset[str]] = {
    # action: read | write | run | mutate | manage_secrets | manage_roles
    "owner": frozenset({"read", "write", "run", "mutate", "manage_secrets",
                        "manage_roles"}),
    "editor": frozenset({"read", "write", "run", "mutate"}),
    "viewer": frozenset({"read"}),
}

ROLE_LABELS: dict[str, str] = {
    "owner": "Владелец — полный доступ",
    "editor": "Редактор — без секретов и смены ролей",
    "viewer": "Гость — только чтение",
}

DEFAULT_ROLE = "owner"


class AccessDenied(RuntimeError):
    """Permission error safe to display in Russian."""


def role_ids() -> list[str]:
    return list(PERMISSIONS)


def role_labels() -> list[str]:
    return [ROLE_LABELS[role] for role in PERMISSIONS]


def role_id_by_label(label: str) -> str:
    for role, text in ROLE_LABELS.items():
        if text == label:
            return role
    return DEFAULT_ROLE


def normalize_role(role: str) -> str:
    return str(role or "").strip().lower() if str(role or "").strip().lower() \
        in PERMISSIONS else DEFAULT_ROLE


def can(role: str, action: str) -> bool:
    return action in PERMISSIONS.get(normalize_role(role), frozenset())


def require(role: str, action: str, what: str = "") -> None:
    if not can(role, action):
        raise AccessDenied(
            "Недостаточно прав: "
            f"роль «{ROLE_LABELS.get(normalize_role(role), role)}» "
            f"не позволяет «{action}»{(' — ' + what) if what else ''}.")


@dataclass(frozen=True)
class RolePolicy:
    role: str = DEFAULT_ROLE

    def can(self, action: str) -> bool:
        return can(self.role, action)

    @property
    def readonly(self) -> bool:
        return not self.can("write")

    @property
    def agent_readonly(self) -> bool:
        return not self.can("mutate")
