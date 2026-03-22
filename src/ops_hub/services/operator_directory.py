"""Operator/admin identity and access resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ops_hub.core.config import Settings
from ops_hub.models.requests import OperatorIdentity, OperatorMappingRecord
from ops_hub.services.operator_mapping_store import OperatorMappingStore


@dataclass(slots=True)
class OperatorDirectoryService:
    """Resolve Discord users into Ops Hub admin/operator identities."""

    settings: Settings
    store: OperatorMappingStore

    def resolve_identity(self, *, user_id: int, role_ids: set[int]) -> OperatorIdentity:
        """Return the current Ops Hub identity for a Discord user."""
        is_admin = user_id in self.settings.admin_user_ids or bool(role_ids & set(self.settings.admin_role_ids))
        is_parts = (
            is_admin
            or user_id in self.settings.parts_user_ids
            or bool(role_ids & set(self.settings.parts_role_ids))
        )
        is_dispatcher = (
            is_admin
            or user_id in self.settings.dispatcher_user_ids
            or bool(role_ids & set(self.settings.dispatcher_role_ids))
        )
        is_operator = (
            is_admin
            or user_id in self.settings.operator_user_ids
            or bool(role_ids & set(self.settings.operator_role_ids))
        )
        return OperatorIdentity(
            discord_user_id=user_id,
            is_admin=is_admin,
            is_operator=is_operator,
            is_parts=is_parts,
            is_dispatcher=is_dispatcher,
            bluefolder_user_id=self.mappings().get(user_id),
        )

    def mappings(self) -> dict[int, int]:
        """Return the merged operator mapping set."""
        merged = dict(self.settings.operator_bluefolder_user_map)
        merged.update(self.store.load())
        return merged

    def mapping_records(self) -> list[OperatorMappingRecord]:
        """Return typed operator mapping records."""
        self.store.records = self.mappings()
        return self.store.current_records()

    def export_mappings(self) -> Path | None:
        """Persist the current merged mappings to disk."""
        return self.store.export(self.mappings())

    def reload_mappings(self) -> dict[int, int]:
        """Reload file-backed mappings and return the merged result."""
        self.store.load()
        return self.mappings()

    def set_mapping(self, *, discord_user_id: int, bluefolder_user_id: int) -> None:
        """Insert or update a mapping in the file-backed store."""
        mappings = self.mappings()
        mappings[discord_user_id] = bluefolder_user_id
        self.store.export(mappings)

    def remove_mapping(self, *, discord_user_id: int) -> bool:
        """Remove a mapping from the file-backed store if present."""
        mappings = self.mappings()
        removed = discord_user_id in mappings
        mappings.pop(discord_user_id, None)
        self.store.export(mappings)
        return removed
