"""Simple dependency container for Ops Hub."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ops_hub.core.config import Settings
from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.integrations.dispatch_adapter import DispatchAdapter
from ops_hub.integrations.parts_cannon_adapter import PartsHandoffAdapter
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.dispatch import DispatchService
from ops_hub.services.notifications import NotificationService
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.operator_mapping_store import OperatorMappingStore
from ops_hub.services.operator_role_store import OperatorRoleStore
from ops_hub.services.parts_cannon import PartsHandoffService
from ops_hub.services.photo_feature_flags import PhotoFeatureFlagsService
from ops_hub.services.photo_feature_store import PhotoFeatureStore
from ops_hub.services.parts_request_store import PartsRequestStore
from ops_hub.services.photo_ingest import PhotoIngestService
from ops_hub.services.service_smith import ServiceSmithService
from ops_hub.services.service_smith_profile_store import ServiceSmithProfileStore
from ops_hub.services.sms import DispatchSmsService, DryRunSmsAdapter, SmsAuditStore, TwilioSmsAdapter
from ops_hub.services.technician_api import TechnicianApiService
from ops_hub.services.workflow_state import WorkflowStateService
from ops_hub.services.workflow_state_store import WorkflowStateStore


@dataclass(slots=True)
class ServiceContainer:
    """Application dependency graph."""

    settings: Settings
    notification_service: NotificationService
    technician_directory_service: TechnicianDirectoryService
    photo_feature_flags_service: PhotoFeatureFlagsService
    bluefolder_service: BlueFolderService
    parts_handoff_service: PartsHandoffService
    photo_ingest_service: PhotoIngestService
    dispatch_service: DispatchService
    technician_api_service: TechnicianApiService
    workflow_state_service: WorkflowStateService
    service_smith_service: ServiceSmithService
    sms_service: DispatchSmsService

    @property
    def parts_cannon_service(self) -> PartsHandoffService:
        """Deprecated compatibility alias for the old codename."""
        return self.parts_handoff_service


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
        role_store=OperatorRoleStore(
            file_path=Path(settings.operator_role_file).expanduser()
            if settings.operator_role_file
            else Path.cwd() / "config" / "operator_roles.json",
        ),
    )
    photo_feature_flags_service = PhotoFeatureFlagsService(
        defaults={
            "mdlsn_upload": settings.enable_mdlsn_upload,
            "photo_archive_handoff": settings.enable_photo_archive_handoff,
            "photo_mailbox_scan": settings.enable_photo_mailbox_scan,
            "weekly_missing_photo_notices": settings.enable_weekly_missing_photo_notices,
        },
        store=PhotoFeatureStore(
            file_path=Path(settings.photo_feature_flags_file).expanduser() if settings.photo_feature_flags_file else None,
        ),
    )

    # Adapters bridge the current local projects into a shared Ops Hub service surface.
    bluefolder_adapter = BlueFolderAdapter(
        base_path=settings.bluefolder_api_path,
        api_key=settings.bluefolder_api_key,
        account_name=settings.bluefolder_account_name,
        base_url=settings.bluefolder_base_url,
        host_header=settings.bluefolder_host_header,
        verify_ssl=settings.bluefolder_verify_ssl,
        timeout_seconds=settings.bluefolder_timeout_seconds,
    )
    parts_adapter = PartsHandoffAdapter(base_path=settings.parts_handoff_project_path)
    parts_request_store = PartsRequestStore(
        file_path=Path(settings.parts_request_file).expanduser() if settings.parts_request_file else None,
    )
    workflow_state_store = WorkflowStateStore(
        file_path=Path(settings.workflow_state_file).expanduser() if settings.workflow_state_file else None,
    )
    service_smith_profile_store = ServiceSmithProfileStore(
        file_path=Path(settings.service_smith_profile_file).expanduser()
        if settings.service_smith_profile_file
        else None,
    )
    sms_audit_store = SmsAuditStore(
        file_path=Path(settings.sms_audit_file).expanduser() if settings.sms_audit_file else None,
    )
    photo_adapter = PhotoIngestAdapter(
        base_path=settings.photo_ingest_project_path,
        bluefolder_api_path=settings.bluefolder_api_path,
        bluefolder_api_key=settings.bluefolder_api_key,
        bluefolder_account_name=settings.bluefolder_account_name,
        bluefolder_base_url=settings.bluefolder_base_url,
        bluefolder_host_header=settings.bluefolder_host_header,
        bluefolder_verify_ssl=settings.bluefolder_verify_ssl,
        bluefolder_timeout_seconds=settings.bluefolder_timeout_seconds,
        compress_max_dimension=settings.photo_compress_max_dimension,
        compress_jpeg_quality=settings.photo_compress_jpeg_quality,
        compress_max_mb=settings.photo_compress_max_mb,
        required_tags=tuple(settings.photo_required_tags),
        archive_smtp_host=settings.photo_archive_smtp_host,
        archive_smtp_port=settings.photo_archive_smtp_port,
        archive_smtp_username=settings.photo_archive_smtp_username,
        archive_smtp_password=settings.photo_archive_smtp_password,
        archive_smtp_use_tls=settings.photo_archive_smtp_use_tls,
        archive_from_email=settings.photo_archive_from_email,
        archive_to_email=settings.photo_archive_to_email,
        mailbox_imap_host=settings.photo_mailbox_imap_host,
        mailbox_imap_port=settings.photo_mailbox_imap_port,
        mailbox_imap_username=settings.photo_mailbox_imap_username,
        mailbox_imap_password=settings.photo_mailbox_imap_password,
        mailbox_imap_use_ssl=settings.photo_mailbox_imap_use_ssl,
        mailbox_folder=settings.photo_mailbox_folder,
        mailbox_search_days=settings.photo_mailbox_search_days,
    )
    dispatch_adapter = DispatchAdapter(
        base_path=settings.dispatch_project_path,
        bluefolder_api_path=settings.bluefolder_api_path,
        bluefolder_api_key=settings.bluefolder_api_key,
        bluefolder_account_name=settings.bluefolder_account_name,
        bluefolder_base_url=settings.bluefolder_base_url,
        bluefolder_host_header=settings.bluefolder_host_header,
        bluefolder_verify_ssl=settings.bluefolder_verify_ssl,
        bluefolder_timeout_seconds=settings.bluefolder_timeout_seconds,
    )
    sms_provider = (settings.sms_provider or "dry_run").strip().lower()
    if sms_provider == "twilio":
        sms_adapter = TwilioSmsAdapter(
            account_sid=settings.sms_twilio_account_sid,
            auth_token=settings.sms_twilio_auth_token,
            from_number=settings.sms_from_number,
            messaging_service_sid=settings.sms_twilio_messaging_service_sid,
        )
    else:
        sms_adapter = DryRunSmsAdapter()
    sms_service = DispatchSmsService(
        adapter=sms_adapter,
        store=sms_audit_store,
        from_label=(settings.sms_from_number or "ARCoM Ops"),
    )

    bluefolder_service = BlueFolderService(
        adapter=bluefolder_adapter,
        notifications=notification_service,
    )
    parts_handoff_service = PartsHandoffService(
        adapter=parts_adapter,
        notifications=notification_service,
        request_store=parts_request_store,
        technician_directory_service=technician_directory_service,
    )
    photo_ingest_service = PhotoIngestService(
        settings=settings,
        adapter=photo_adapter,
        feature_flags=photo_feature_flags_service,
        bluefolder_service=bluefolder_service,
        technician_directory_service=technician_directory_service,
        notifications=notification_service,
    )
    workflow_state_service = WorkflowStateService(
        store=workflow_state_store,
        bluefolder_service=bluefolder_service,
        parts_cannon_service=parts_handoff_service,
        technician_directory_service=technician_directory_service,
        notification_service=notification_service,
        photo_ingest_service=photo_ingest_service,
    )
    bluefolder_service.workflow_state_service = workflow_state_service
    parts_handoff_service.workflow_state_service = workflow_state_service

    return ServiceContainer(
        settings=settings,
        notification_service=notification_service,
        technician_directory_service=technician_directory_service,
        photo_feature_flags_service=photo_feature_flags_service,
        bluefolder_service=bluefolder_service,
        parts_handoff_service=parts_handoff_service,
        photo_ingest_service=photo_ingest_service,
        dispatch_service=DispatchService(
            adapter=dispatch_adapter,
            bluefolder_service=BlueFolderService(adapter=bluefolder_adapter),
            technician_directory_service=technician_directory_service,
            workflow_state_service=workflow_state_service,
            sms_service=sms_service,
            persistent_cache_path=Path(settings.dispatch_cache_file).expanduser()
            if settings.dispatch_cache_file
            else None,
        ),
        technician_api_service=TechnicianApiService(
            bluefolder_service=bluefolder_service,
            technician_directory_service=technician_directory_service,
            parts_cannon_service=parts_handoff_service,
            photo_ingest_service=photo_ingest_service,
            workflow_state_service=workflow_state_service,
        ),
        workflow_state_service=workflow_state_service,
        service_smith_service=ServiceSmithService(
            settings=settings,
            profile_store=service_smith_profile_store,
        ),
        sms_service=sms_service,
    )
