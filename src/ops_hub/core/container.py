"""Simple dependency container for Ops Hub."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ops_hub.core.config import Settings
from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.dispatch import DispatchService
from ops_hub.services.notifications import NotificationService
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.operator_mapping_store import OperatorMappingStore
from ops_hub.services.parts_cannon import PartsCannonService
from ops_hub.services.parts_request_store import PartsRequestStore
from ops_hub.services.photo_ingest import PhotoIngestService


@dataclass(slots=True)
class ServiceContainer:
    """Application dependency graph."""

    settings: Settings
    notification_service: NotificationService
    technician_directory_service: TechnicianDirectoryService
    bluefolder_service: BlueFolderService
    parts_cannon_service: PartsCannonService
    photo_ingest_service: PhotoIngestService
    dispatch_service: DispatchService


def build_container(settings: Settings) -> ServiceContainer:
    """Build services and adapters for the app runtime."""
    notification_service = NotificationService(
        channel_id=settings.notification_channel_id,
        channel_map=settings.notification_channel_map,
    )
    technician_directory_service = TechnicianDirectoryService(
        settings=settings,
        store=OperatorMappingStore(
            file_path=Path(settings.technician_mapping_file).expanduser() if settings.technician_mapping_file else None,
        ),
    )

    # TODO: Replace these placeholders with real wrappers around existing local projects.
    bluefolder_adapter = BlueFolderAdapter(
        base_path=settings.bluefolder_api_path,
        api_key=settings.bluefolder_api_key,
        account_name=settings.bluefolder_account_name,
        base_url=settings.bluefolder_base_url,
        host_header=settings.bluefolder_host_header,
        verify_ssl=settings.bluefolder_verify_ssl,
        timeout_seconds=settings.bluefolder_timeout_seconds,
    )
    parts_adapter = PartsCannonAdapter(base_path=settings.parts_cannon_project_path)
    parts_request_store = PartsRequestStore(
        file_path=Path(settings.parts_request_file).expanduser() if settings.parts_request_file else None,
    )
    photo_adapter = PhotoIngestAdapter(base_path=settings.photo_ingest_project_path)
    dispatch_adapter = DispatchAdapter(base_path=settings.dispatch_project_path)

    return ServiceContainer(
        settings=settings,
        notification_service=notification_service,
        technician_directory_service=technician_directory_service,
        bluefolder_service=BlueFolderService(adapter=bluefolder_adapter),
        parts_cannon_service=PartsCannonService(
            adapter=parts_adapter,
            notifications=notification_service,
            request_store=parts_request_store,
        ),
        photo_ingest_service=PhotoIngestService(settings=settings, adapter=photo_adapter),
        dispatch_service=DispatchService(
            adapter=dispatch_adapter,
            bluefolder_service=BlueFolderService(adapter=bluefolder_adapter),
        ),
    )
