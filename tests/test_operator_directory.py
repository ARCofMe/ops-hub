from __future__ import annotations

import asyncio
import json

from ops_hub.core.config import Settings
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.operator_mapping_store import OperatorMappingStore
from ops_hub.services.operator_role_store import OperatorRoleStore


def test_mapping_records_include_member_export_identity(tmp_path) -> None:
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    (exports_dir / "discord_members_member_map_20260405T180000Z.json").write_text(
        json.dumps(
            {
                "members": [
                    {
                        "discord_user_id": "42",
                        "username": "dispatch.user",
                        "display_name": "Dispatch Dave",
                        "global_name": "dave",
                        "role_names": ["Dispatch"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        discord_token="token",
        member_export_path=str(exports_dir / "discord_members.json"),
        technician_bluefolder_user_map={42: 9001},
    )
    service = TechnicianDirectoryService(settings=settings, store=OperatorMappingStore())

    records = service.mapping_records()

    assert len(records) == 1
    assert records[0].display_name == "Dispatch Dave"
    assert records[0].username == "dispatch.user"
    assert records[0].role_names == ("Dispatch",)
    assert service.display_label(42) == "Dispatch Dave"
    assert service.technician_display_label(bluefolder_user_id=9001) == "Dispatch Dave"


def test_operator_records_include_unmapped_bluefolder_users(tmp_path) -> None:
    settings = Settings(
        discord_token="token",
        technician_bluefolder_user_map={42: 9001},
    )
    service = TechnicianDirectoryService(settings=settings, store=OperatorMappingStore())

    class _BlueFolderService:
        async def get_operator_profiles(self) -> dict[int, dict[str, str | None]]:
            return {
                9001: {"name": "Dispatch Dave", "user_type": "Dispatch", "role": "dispatch"},
                9002: {"name": "Field Sam", "user_type": "Technician", "role": "technician"},
            }

    records = asyncio.run(service.operator_records(bluefolder_service=_BlueFolderService()))

    assert [(record.discord_user_id, record.bluefolder_user_id, record.bluefolder_name) for record in records] == [
        (42, 9001, "Dispatch Dave"),
        (None, 9002, "Field Sam"),
    ]
    assert records[0].bluefolder_role == "dispatch"
    assert records[1].bluefolder_role == "technician"


def test_operator_records_merge_recent_assigned_directory(tmp_path) -> None:
    settings = Settings(discord_token="token")
    service = TechnicianDirectoryService(settings=settings, store=OperatorMappingStore())

    class _BlueFolderService:
        async def get_operator_profiles(self) -> dict[int, dict[str, str | None]]:
            return {
                9003: {"name": "Route Pat", "user_type": "Technician", "role": "technician"},
                9004: {"name": "Field Sam", "user_type": "Technician", "role": "technician"},
            }

    records = asyncio.run(service.operator_records(bluefolder_service=_BlueFolderService()))

    assert [(record.discord_user_id, record.bluefolder_user_id, record.bluefolder_name) for record in records] == [
        (None, 9004, "Field Sam"),
        (None, 9003, "Route Pat"),
    ]


def test_operator_records_apply_bluefolder_role_override(tmp_path) -> None:
    settings = Settings(discord_token="token")
    role_file = tmp_path / "operator_roles.json"
    role_file.write_text('{"33491758": "parts"}', encoding="utf-8")
    service = TechnicianDirectoryService(
        settings=settings,
        store=OperatorMappingStore(),
        role_store=OperatorRoleStore(file_path=role_file),
    )

    class _BlueFolderService:
        async def get_operator_profiles(self) -> dict[int, dict[str, object]]:
            return {
                33491758: {
                    "name": "Paul J Powell",
                    "user_type": "Technician",
                    "role": "technician",
                    "roles": ("Lead Technician", "Scheduler", "Technician"),
                }
            }

    records = asyncio.run(service.operator_records(bluefolder_service=_BlueFolderService()))

    assert len(records) == 1
    assert records[0].bluefolder_role == "parts"
    assert records[0].bluefolder_roles == ("Lead Technician", "Scheduler", "Technician")


def test_dispatch_owner_records_include_dispatch_admin_and_parts_roles(tmp_path) -> None:
    settings = Settings(discord_token="token")
    service = TechnicianDirectoryService(
        settings=settings,
        store=OperatorMappingStore(),
        role_store=OperatorRoleStore(file_path=tmp_path / "operator_roles.json", records={33491758: "parts"}),
    )

    class _BlueFolderService:
        async def get_operator_profiles(self) -> dict[int, dict[str, object]]:
            return {
                1001: {"name": "Dispatch Dana", "user_type": "Dispatch", "role": "dispatch", "roles": ("Scheduler",)},
                1002: {"name": "Admin Alex", "user_type": "Admin", "role": "admin", "roles": ("Administrator",)},
                1003: {"name": "Field Fran", "user_type": "Technician", "role": "technician", "roles": ("Technician",)},
                33491758: {"name": "Paul J Powell", "user_type": "Technician", "role": "technician", "roles": ("Lead Technician",)},
            }

    records = asyncio.run(service.dispatch_owner_records(bluefolder_service=_BlueFolderService()))

    assert [(record.bluefolder_user_id, record.bluefolder_role) for record in records] == [
        (1002, "admin"),
        (1001, "dispatch"),
        (33491758, "parts"),
    ]
