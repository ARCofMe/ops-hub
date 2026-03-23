"""Technician/admin identity and access resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ops_hub.core.config import Settings
from ops_hub.models.requests import TechnicianIdentity, TechnicianMappingRecord
from ops_hub.services.operator_mapping_store import OperatorMappingStore


@dataclass(slots=True)
class TechnicianDirectoryService:
    """Resolve Discord users into Ops Hub admin/technician identities."""

    settings: Settings
    store: OperatorMappingStore

    def resolve_identity(self, *, user_id: int, role_ids: set[int]) -> TechnicianIdentity:
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
        is_technician = (
            is_admin
            or user_id in self.settings.technician_user_ids
            or bool(role_ids & set(self.settings.technician_role_ids))
        )
        return TechnicianIdentity(
            discord_user_id=user_id,
            is_admin=is_admin,
            is_technician=is_technician,
            is_parts=is_parts,
            is_dispatcher=is_dispatcher,
            bluefolder_user_id=self.mappings().get(user_id),
        )

    def mappings(self) -> dict[int, int]:
        """Return the merged technician mapping set."""
        merged = dict(self.settings.technician_bluefolder_user_map)
        merged.update(self.store.load())
        return merged

    def mapping_records(self) -> list[TechnicianMappingRecord]:
        """Return typed technician mapping records."""
        self.store.records = self.mappings()
        return self.store.current_records()

    def reverse_mappings(self) -> dict[int, int]:
        """Return BlueFolder-to-Discord technician mappings."""
        return {bluefolder_user_id: discord_user_id for discord_user_id, bluefolder_user_id in self.mappings().items()}

    def discord_mention(self, discord_user_id: int) -> str:
        """Return a Discord mention string for a user id."""
        return f"<@{discord_user_id}>"

    def technician_label(
        self,
        *,
        discord_user_id: int | None = None,
        bluefolder_user_id: int | None = None,
    ) -> str:
        """Render the best available technician label for Discord-facing messages."""
        resolved_discord_user_id = discord_user_id
        if resolved_discord_user_id is None and bluefolder_user_id is not None:
            resolved_discord_user_id = self.reverse_mappings().get(bluefolder_user_id)

        if resolved_discord_user_id is not None and bluefolder_user_id is not None:
            return f"{self.discord_mention(resolved_discord_user_id)} (BlueFolder `{bluefolder_user_id}`)"
        if resolved_discord_user_id is not None:
            return self.discord_mention(resolved_discord_user_id)
        if bluefolder_user_id is not None:
            return f"BlueFolder user `{bluefolder_user_id}`"
        return "Unknown technician"

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
