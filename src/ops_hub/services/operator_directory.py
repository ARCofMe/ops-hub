"""Technician/admin identity and access resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ops_hub.core.config import Settings
from ops_hub.models.requests import DiscordMemberRecord, TechnicianIdentity, TechnicianMappingRecord
from ops_hub.services.operator_mapping_store import OperatorMappingStore
from ops_hub.services.operator_role_store import OperatorRoleStore

if TYPE_CHECKING:
    from ops_hub.services.bluefolder import BlueFolderService


@dataclass(slots=True)
class TechnicianDirectoryService:
    """Resolve Discord users into Ops Hub admin/technician identities."""

    settings: Settings
    store: OperatorMappingStore
    role_store: OperatorRoleStore = field(default_factory=OperatorRoleStore)

    def resolve_identity(
        self,
        *,
        user_id: int,
        role_ids: set[int],
        has_administrator_permission: bool = False,
        is_guild_owner: bool = False,
    ) -> TechnicianIdentity:
        """Return the current Ops Hub identity for a Discord user."""
        is_admin = (
            user_id in self.settings.admin_user_ids
            or bool(role_ids & set(self.settings.admin_role_ids))
            or has_administrator_permission
            or is_guild_owner
        )
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
        member_directory = self.member_directory()
        return [
            TechnicianMappingRecord(
                discord_user_id=record.discord_user_id,
                bluefolder_user_id=record.bluefolder_user_id,
                bluefolder_name=None,
                username=member_directory.get(record.discord_user_id).username if record.discord_user_id in member_directory else None,
                display_name=member_directory.get(record.discord_user_id).display_name if record.discord_user_id in member_directory else None,
                global_name=member_directory.get(record.discord_user_id).global_name if record.discord_user_id in member_directory else None,
                role_names=member_directory.get(record.discord_user_id).role_names if record.discord_user_id in member_directory else (),
            )
            for record in self.store.current_records()
        ]

    async def operator_records(
        self,
        *,
        bluefolder_service: "BlueFolderService | None" = None,
    ) -> list[TechnicianMappingRecord]:
        """Return BlueFolder-first operator records with optional Discord linkage."""
        bluefolder_profiles = await bluefolder_service.get_operator_profiles() if bluefolder_service is not None else {}
        if not bluefolder_profiles and bluefolder_service is not None:
            bluefolder_directory = await bluefolder_service.get_operator_directory()
            bluefolder_profiles = {
                user_id: {"name": name, "user_type": None, "role": None, "roles": ()}
                for user_id, name in bluefolder_directory.items()
            }
        return self._operator_records_from_directory(bluefolder_profiles)

    async def dispatch_owner_records(
        self,
        *,
        bluefolder_service: "BlueFolderService | None" = None,
    ) -> list[TechnicianMappingRecord]:
        """Return BlueFolder-backed operators who can own dispatch follow-up work."""
        records = await self.operator_records(bluefolder_service=bluefolder_service)
        return [record for record in records if self.is_dispatch_owner_record(record)]

    @staticmethod
    def is_routeable_technician_record(record: TechnicianMappingRecord) -> bool:
        """Return whether a record should appear as a routeable field technician."""
        if record.bluefolder_role is None and not record.bluefolder_roles:
            return True
        if record.bluefolder_role in {"parts", "admin"}:
            return False
        normalized_roles = {
            str(role or "").strip().casefold()
            for role in record.bluefolder_roles
            if str(role or "").strip()
        }
        if normalized_roles & {"lead technician", "technician", "subcontractor"}:
            return True
        return record.bluefolder_role == "technician"

    @staticmethod
    def is_dispatch_owner_record(record: TechnicianMappingRecord) -> bool:
        """Return whether a record can own dispatch follow-up work."""
        if record.bluefolder_role in {"dispatch", "admin", "parts"}:
            return True
        normalized_roles = {
            str(role or "").strip().casefold()
            for role in record.bluefolder_roles
            if str(role or "").strip()
        }
        return bool(normalized_roles & {"administrator", "bookkeeper", "scheduler", "service manager", "sales"})

    def reverse_mappings(self) -> dict[int, int]:
        """Return BlueFolder-to-Discord technician mappings."""
        return {bluefolder_user_id: discord_user_id for discord_user_id, bluefolder_user_id in self.mappings().items()}

    def discord_mention(self, discord_user_id: int) -> str:
        """Return a Discord mention string for a user id."""
        return f"<@{discord_user_id}>"

    def member_directory(self) -> dict[int, DiscordMemberRecord]:
        """Load the latest exported Discord member directory when available."""
        path = self._latest_member_export_path()
        if path is None or not path.exists():
            return {}

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        members = payload.get("members") if isinstance(payload, dict) else None
        if not isinstance(members, list):
            return {}

        directory: dict[int, DiscordMemberRecord] = {}
        for member in members:
            if not isinstance(member, dict):
                continue
            raw_user_id = str(member.get("discord_user_id") or "").strip()
            if not raw_user_id.isdigit():
                continue
            user_id = int(raw_user_id)
            role_names = member.get("role_names")
            directory[user_id] = DiscordMemberRecord(
                discord_user_id=user_id,
                username=str(member.get("username") or "").strip() or None,
                display_name=str(member.get("display_name") or "").strip() or None,
                global_name=str(member.get("global_name") or "").strip() or None,
                role_names=tuple(str(role).strip() for role in role_names if str(role).strip()) if isinstance(role_names, list) else (),
            )
        return directory

    def display_label(self, discord_user_id: int | None) -> str | None:
        """Return the best available human-readable Discord identity label."""
        if discord_user_id is None:
            return None
        member = self.member_directory().get(discord_user_id)
        if member is not None:
            for value in (member.display_name, member.global_name, member.username):
                if value:
                    return value
        return str(discord_user_id)

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

    def technician_display_label(
        self,
        *,
        discord_user_id: int | None = None,
        bluefolder_user_id: int | None = None,
    ) -> str | None:
        """Return the best available non-mention label for API and web surfaces."""
        resolved_discord_user_id = discord_user_id
        if resolved_discord_user_id is None and bluefolder_user_id is not None:
            resolved_discord_user_id = self.reverse_mappings().get(bluefolder_user_id)

        display_label = self.display_label(resolved_discord_user_id)
        if display_label:
            return display_label
        if bluefolder_user_id is not None:
            return f"Tech {bluefolder_user_id}"
        if resolved_discord_user_id is not None:
            return str(resolved_discord_user_id)
        return None

    def _operator_records_from_directory(
        self,
        bluefolder_profiles: dict[int, dict[str, object]],
    ) -> list[TechnicianMappingRecord]:
        """Merge active BlueFolder users with optional Discord-linked metadata."""
        role_overrides = self.role_store.load()
        bluefolder_to_discord_ids: dict[int, list[int]] = {}
        for discord_user_id, bluefolder_user_id in self.mappings().items():
            bluefolder_to_discord_ids.setdefault(bluefolder_user_id, []).append(discord_user_id)
        member_directory = self.member_directory()
        known_bluefolder_ids = set(bluefolder_to_discord_ids)
        known_bluefolder_ids.update(int(user_id) for user_id in bluefolder_profiles)

        records: list[TechnicianMappingRecord] = []
        for bluefolder_user_id in sorted(
            known_bluefolder_ids,
            key=lambda user_id: (str((bluefolder_profiles.get(user_id) or {}).get("name") or "").casefold(), user_id),
        ):
            discord_user_id = next(iter(sorted(bluefolder_to_discord_ids.get(bluefolder_user_id, []))), None)
            member = member_directory.get(discord_user_id) if discord_user_id is not None else None
            bluefolder_profile = bluefolder_profiles.get(bluefolder_user_id) or {}
            effective_role = str(
                role_overrides.get(bluefolder_user_id)
                or bluefolder_profile.get("role")
                or ""
            ).strip() or None
            bluefolder_roles = tuple(
                str(role).strip() for role in (bluefolder_profile.get("roles") or ()) if str(role).strip()
            )
            records.append(
                TechnicianMappingRecord(
                    discord_user_id=discord_user_id,
                    bluefolder_user_id=bluefolder_user_id,
                    bluefolder_name=str(bluefolder_profile.get("name") or "").strip() or None,
                    bluefolder_user_type=str(bluefolder_profile.get("user_type") or "").strip() or None,
                    bluefolder_role=effective_role,
                    bluefolder_roles=bluefolder_roles,
                    username=member.username if member is not None else None,
                    display_name=member.display_name if member is not None else None,
                    global_name=member.global_name if member is not None else None,
                    role_names=member.role_names if member is not None else (),
                )
            )
        return records

    def _latest_member_export_path(self) -> Path | None:
        """Return the newest member-map export path when available."""
        configured = self.settings.member_export_path
        base_path = Path(configured).expanduser() if configured else Path.cwd() / "exports" / "discord_members.json"
        candidates = sorted(
            base_path.parent.glob(f"{base_path.stem}_member_map*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
        if base_path.exists():
            return base_path
        return None

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

    def import_mappings(self, records: dict[int, int], *, replace: bool = False) -> Path | None:
        """Import many mappings into the file-backed store."""
        mappings = dict(records) if replace else self.mappings()
        if not replace:
            mappings.update(records)
        return self.store.export(mappings)

    def remove_mapping(self, *, discord_user_id: int) -> bool:
        """Remove a mapping from the file-backed store if present."""
        mappings = self.mappings()
        removed = discord_user_id in mappings
        mappings.pop(discord_user_id, None)
        self.store.export(mappings)
        return removed
