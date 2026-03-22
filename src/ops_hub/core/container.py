"""Simple dependency container for Ops Hub."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.core.config import Settings
from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.integrations.parts_cannon_adapter import PartsCannonAdapter
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.dispatch import DispatchService
from ops_hub.services.notifications import NotificationService
from ops_hub.services.parts_cannon import PartsCannonService
from ops_hub.services.photo_ingest import PhotoIngestService


@dataclass(slots=True)
class ServiceContainer:
    """Application dependency graph."""

    settings: Settings
    notification_service: NotificationService
    bluefolder_service: BlueFolderService
    parts_cannon_service: PartsCannonService
    photo_ingest_service: PhotoIngestService
    dispatch_service: DispatchService


def build_container(settings: Settings) -> ServiceContainer:
    """Build services and adapters for the app runtime."""
    notification_service = NotificationService()

    # TODO: Replace these placeholders with real wrappers around existing local projects.
    bluefolder_adapter = BlueFolderAdapter(base_path=settings.bluefolder_api_path)
    parts_adapter = PartsCannonAdapter(base_path=settings.parts_cannon_project_path)
    photo_adapter = PhotoIngestAdapter(base_path=settings.photo_ingest_project_path)
    dispatch_adapter = DispatchAdapter(base_path=settings.dispatch_project_path)

    return ServiceContainer(
        settings=settings,
        notification_service=notification_service,
        bluefolder_service=BlueFolderService(adapter=bluefolder_adapter),
        parts_cannon_service=PartsCannonService(adapter=parts_adapter, notifications=notification_service),
        photo_ingest_service=PhotoIngestService(adapter=photo_adapter),
        dispatch_service=DispatchService(
            adapter=dispatch_adapter,
            bluefolder_service=BlueFolderService(adapter=bluefolder_adapter),
        ),
    )

