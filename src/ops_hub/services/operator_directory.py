"""Operator/admin identity and access resolution."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.core.config import Settings
from ops_hub.models.requests import OperatorIdentity


@dataclass(slots=True)
class OperatorDirectoryService:
    """Resolve Discord users into Ops Hub admin/operator identities."""

    settings: Settings

    def resolve_identity(self, *, user_id: int, role_ids: set[int]) -> OperatorIdentity:
        """Return the current Ops Hub identity for a Discord user."""
        is_admin = user_id in self.settings.admin_user_ids or bool(role_ids & set(self.settings.admin_role_ids))
        is_operator = (
            is_admin
            or user_id in self.settings.operator_user_ids
            or bool(role_ids & set(self.settings.operator_role_ids))
        )
        return OperatorIdentity(
            discord_user_id=user_id,
            is_admin=is_admin,
            is_operator=is_operator,
            bluefolder_user_id=self.settings.operator_bluefolder_user_map.get(user_id),
        )
