"""Dependency-container wiring tests for Ops Hub."""

from __future__ import annotations

from pathlib import Path

from ops_hub.core.config import Settings
from ops_hub.core.container import build_container


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
        "parts_request_file": None,
        "workflow_state_file": None,
        "service_smith_profile_file": None,
        "photo_feature_flags_file": None,
        "notification_channel_id": None,
        "notification_channel_map": {},
        "log_level": "INFO",
        "environment": "dev",
        "photo_ingest_channel_id": None,
        "bluefolder_api_path": None,
        "bluefolder_api_key": None,
        "bluefolder_account_name": None,
        "bluefolder_base_url": None,
        "bluefolder_host_header": None,
        "bluefolder_verify_ssl": None,
        "bluefolder_timeout_seconds": None,
        "bluebot_discord_extension_path": None,
        "photo_ingest_project_path": None,
        "parts_cannon_project_path": None,
        "dispatch_project_path": None,
        "enable_mdlsn_upload": True,
        "enable_photo_archive_handoff": False,
        "enable_photo_mailbox_scan": True,
        "enable_weekly_missing_photo_notices": False,
        "photo_compress_max_dimension": 1600,
        "photo_compress_jpeg_quality": 82,
        "photo_compress_max_mb": 5.0,
        "photo_required_tags": ["Model", "Serial"],
        "photo_archive_smtp_host": None,
        "photo_archive_smtp_port": 587,
        "photo_archive_smtp_username": None,
        "photo_archive_smtp_password": None,
        "photo_archive_smtp_use_tls": True,
        "photo_archive_from_email": None,
        "photo_archive_to_email": None,
        "photo_mailbox_imap_host": None,
        "photo_mailbox_imap_port": 993,
        "photo_mailbox_imap_username": None,
        "photo_mailbox_imap_password": None,
        "photo_mailbox_imap_use_ssl": True,
        "photo_mailbox_folder": "INBOX",
        "photo_mailbox_search_days": 14,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_container_expands_store_paths_and_feature_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = _settings(
        technician_mapping_file="~/tech-map.json",
        parts_request_file="~/parts-requests.json",
        workflow_state_file="~/workflow-state.json",
        service_smith_profile_file="~/service-smith-profiles.json",
        photo_feature_flags_file="~/photo-flags.json",
        notification_channel_id=321,
        notification_channel_map={"parts": 200},
        enable_mdlsn_upload=False,
        enable_photo_archive_handoff=True,
        enable_photo_mailbox_scan=False,
        enable_weekly_missing_photo_notices=True,
    )

    container = build_container(settings)

    assert container.notification_service.channel_id == 321
    assert container.notification_service.channel_map == {"parts": 200}
    assert container.technician_directory_service.store.file_path == tmp_path / "tech-map.json"
    assert container.parts_cannon_service.request_store.file_path == tmp_path / "parts-requests.json"
    assert container.workflow_state_service.store.file_path == tmp_path / "workflow-state.json"
    assert container.service_smith_service.profile_store.file_path == tmp_path / "service-smith-profiles.json"
    assert container.photo_feature_flags_service.store.file_path == tmp_path / "photo-flags.json"
    assert container.photo_feature_flags_service.defaults == {
        "mdlsn_upload": False,
        "photo_archive_handoff": True,
        "photo_mailbox_scan": False,
        "weekly_missing_photo_notices": True,
    }


def test_build_container_shares_expected_collaborators() -> None:
    settings = _settings(technician_mapping_file=None, parts_request_file=None, photo_feature_flags_file=None)

    container = build_container(settings)

    assert container.bluefolder_service.notifications is container.notification_service
    assert container.photo_ingest_service.notifications is container.notification_service
    assert container.photo_ingest_service.feature_flags is container.photo_feature_flags_service
    assert container.parts_cannon_service.notifications is container.notification_service
    assert container.parts_cannon_service.technician_directory_service is container.technician_directory_service
    assert container.parts_cannon_service.workflow_state_service is container.workflow_state_service
    assert container.bluefolder_service.workflow_state_service is container.workflow_state_service
    assert container.dispatch_service.workflow_state_service is container.workflow_state_service
    assert container.dispatch_service.technician_directory_service is container.technician_directory_service
    assert container.photo_ingest_service.technician_directory_service is container.technician_directory_service
    assert container.bluefolder_service.adapter is container.photo_ingest_service.bluefolder_service.adapter
    assert container.bluefolder_service.adapter is container.dispatch_service.bluefolder_service.adapter
    assert container.service_smith_service is not None
