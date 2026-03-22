"""Technician mapping store and directory tests for Ops Hub."""

from __future__ import annotations

from pathlib import Path

from ops_hub.core.config import Settings
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.operator_mapping_store import OperatorMappingStore


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": None,
        "admin_user_ids": [],
        "admin_role_ids": [],
        "technician_user_ids": [],
        "technician_role_ids": [],
        "parts_user_ids": [],
        "parts_role_ids": [],
        "dispatcher_user_ids": [],
        "dispatcher_role_ids": [],
        "technician_bluefolder_user_map": {},
        "technician_mapping_file": None,
        "log_level": "INFO",
        "environment": "dev",
        "photo_ingest_channel_id": None,
        "bluefolder_api_path": None,
        "bluefolder_api_key": None,
        "bluefolder_account_name": None,
        "bluefolder_base_url": None,
        "bluebot_discord_extension_path": None,
        "photo_ingest_project_path": None,
        "parts_cannon_project_path": None,
        "dispatch_project_path": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_technician_directory_merges_env_and_file_mappings(tmp_path: Path) -> None:
    file_path = tmp_path / "technician-mappings.json"
    file_path.write_text('{"42": 13051}', encoding="utf-8")
    service = TechnicianDirectoryService(
        settings=_settings(technician_bluefolder_user_map={99: 22222}),
        store=OperatorMappingStore(file_path=file_path),
    )

    mappings = service.mappings()

    assert mappings == {99: 22222, 42: 13051}


def test_technician_directory_exports_mappings(tmp_path: Path) -> None:
    file_path = tmp_path / "technician-mappings.json"
    service = TechnicianDirectoryService(
        settings=_settings(technician_bluefolder_user_map={42: 13051}),
        store=OperatorMappingStore(file_path=file_path),
    )

    exported = service.export_mappings()

    assert exported == file_path
    assert file_path.read_text(encoding="utf-8").strip() == '{\n  "42": 13051\n}'


def test_technician_directory_set_mapping_updates_runtime_without_file() -> None:
    service = TechnicianDirectoryService(
        settings=_settings(),
        store=OperatorMappingStore(file_path=None),
    )

    service.set_mapping(discord_user_id=42, bluefolder_user_id=13051)

    assert service.mappings() == {42: 13051}
