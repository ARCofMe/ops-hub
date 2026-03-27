"""Request and response models used across services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class JobLookupRequest:
    """Input for job lookup operations."""

    reference: str | None
    requested_by_user_id: int
    technician_bluefolder_user_id: int | None = None
    target_bluefolder_user_id: int | None = None
    requester_is_admin: bool = False
    route_origin_address: str | None = None
    route_destination_address: str | None = None


@dataclass(slots=True)
class PartLookupRequest:
    """Input for parts lookup operations."""

    reference: str
    requested_by_user_id: int
    technician_bluefolder_user_id: int | None = None
    requester_is_admin: bool = False


@dataclass(slots=True)
class PartRequestCreate:
    """Input for creating a parts request."""

    reference: str
    description: str
    requested_by_user_id: int
    technician_bluefolder_user_id: int | None = None
    requester_is_admin: bool = False


@dataclass(slots=True)
class PartRequestUpdate:
    """Input for updating a parts request status."""

    request_id: int
    status: str
    updated_by_user_id: int


@dataclass(slots=True)
class PartRequestClaim:
    """Input for claiming or unclaiming a parts request."""

    request_id: int
    parts_user_id: int | None
    updated_by_user_id: int


@dataclass(slots=True)
class CommandResult:
    """Simple user-facing command response."""

    message: str


@dataclass(slots=True)
class RouteMapResult:
    """User-facing route preview payload with optional map assets."""

    message: str
    route_url: str | None = None
    image_url: str | None = None


@dataclass(slots=True)
class NotificationRecord:
    """A single notification attempt captured by the notification service."""

    topic: str
    message: str
    delivery: str


@dataclass(slots=True)
class NotificationStatus:
    """Operational status for the notification service."""

    configured: bool
    mode: str
    transport: str
    notice_count: int
    last_topic: str | None = None


@dataclass(slots=True)
class PartsRequestQueueSummary:
    """Operational summary of the tracked parts request queue."""

    total_requests: int
    open_requests: int
    assigned_requests: int
    unassigned_requests: int
    synced_requests: int
    requested_count: int
    ordered_count: int
    received_count: int
    resolved_count: int
    cancelled_count: int


@dataclass(slots=True)
class TechnicianIdentity:
    """Resolved technician/admin identity for a Discord user."""

    discord_user_id: int
    is_admin: bool
    is_technician: bool
    is_parts: bool
    is_dispatcher: bool
    bluefolder_user_id: int | None = None

    @property
    def is_operator(self) -> bool:
        """Backward-compatible alias for older operator wording."""
        return self.is_technician


@dataclass(slots=True)
class TechnicianMappingRecord:
    """Persistent mapping record for a Discord technician."""

    discord_user_id: int
    bluefolder_user_id: int


@dataclass(slots=True)
class DispatchJobSummary:
    """Read-only summary of dispatch-wrapper availability and lookup state."""

    reference: str
    available: bool
    integration_status: str
    message: str
    source_path: Path | None = None
    module_name: str | None = None
    stop_label: str | None = None
    stop_address: str | None = None
    stop_window: str | None = None
    technician_assignment_status: str | None = None
    technician_origin_address: str | None = None


@dataclass(slots=True)
class BlueFolderJobSummary:
    """Read-only job summary placeholder for future BlueFolder integration."""

    reference: str
    available: bool
    integration_status: str
    message: str
    source_path: Path | None = None
    service_request_id: str | None = None
    subject: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_id: str | None = None
    customer_location_id: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    service_request_status: str | None = None
    customer_contacts: tuple["CustomerContactSummary", ...] = ()


@dataclass(slots=True)
class CustomerContactSummary:
    """A customer contact option for an SR/customer."""

    name: str
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    is_primary: bool = False


@dataclass(slots=True)
class PartsCommentRecord:
    """A BlueFolder comment relevant to the parts workflow."""

    author: str | None
    date_created: str | None
    text: str
    is_visible_to_customer: bool


@dataclass(slots=True)
class PartsLifecycleSnapshot:
    """Normalized summary of the current parts lifecycle state for an SR."""

    stage: str
    stage_label: str
    latest_status_text: str | None = None
    latest_status_author: str | None = None
    latest_status_at: str | None = None
    latest_issue_type: str | None = None
    latest_issue_text: str | None = None
    latest_issue_author: str | None = None
    latest_issue_at: str | None = None


@dataclass(slots=True)
class PhotoIngestMessage:
    """Minimal Discord message data passed into the photo-ingest service."""

    channel_id: int
    message_id: int
    author_id: int
    content: str
    attachment_count: int
    author_label: str | None = None
    attachments: list["PhotoAttachmentPayload"] = field(default_factory=list)


@dataclass(slots=True)
class PhotoIngestResult:
    """Result for photo-ingest message handling."""

    handled: bool
    status: str
    message: str


@dataclass(slots=True)
class PhotoAttachmentPayload:
    """Attachment payload passed from Discord into the photo service."""

    filename: str
    content_type: str | None
    data: bytes


@dataclass(slots=True)
class PhotoArchiveResult:
    """Result payload for photo archive operations."""

    ok: bool
    status: str
    message: str


@dataclass(slots=True)
class ArchivedPhotoRecord:
    """A photo-bearing mailbox record matched to a service request."""

    subject: str
    from_email: str | None
    received_at: str | None
    attachment_count: int
    attachment_names: list[str]


@dataclass(slots=True)
class PhotoComplianceSummary:
    """Read-only summary of mailbox-backed photo compliance for a service request."""

    sr_id: int
    mailbox_status: str
    message: str
    matched_records: list[ArchivedPhotoRecord]
    total_photos: int
    found_tags: list[str]
    missing_tags: list[str]


@dataclass(slots=True)
class PhotoReminderEvaluation:
    """Decision payload for a photo reminder check."""

    sr_id: int
    service_request_status: str | None
    matched_required_status: bool
    missing_photos: bool
    technician_discord_user_id: int | None
    should_notify: bool
    reason: str


@dataclass(slots=True)
class PartsWorkflowSummary:
    """Placeholder summary for a future parts workflow wrapper."""

    reference: str
    available: bool
    integration_status: str
    message: str
    source_path: Path | None = None


@dataclass(slots=True)
class PartsExportSummary:
    """Summary of exporting tracked parts requests to a downstream handoff file."""

    available: bool
    integration_status: str
    message: str
    exported_count: int
    export_path: Path | None = None


@dataclass(slots=True)
class PartsReceiptRecord:
    """A downstream receipt update for a tracked parts request."""

    request_id: int
    status: str
    note: str | None = None


@dataclass(slots=True)
class PartsImportSummary:
    """Summary of importing downstream receipt updates into Ops Hub."""

    available: bool
    integration_status: str
    message: str
    imported_count: int
    receipt_path: Path | None = None
    receipts: list[PartsReceiptRecord] | None = None


@dataclass(slots=True)
class PartRequestRecord:
    """Persistent parts request record."""

    request_id: int
    reference: str
    description: str
    requested_by_user_id: int
    technician_bluefolder_user_id: int | None
    assigned_parts_user_id: int | None
    status: str
    created_at: str
    updated_at: str
    last_synced_at: str | None = None
    last_reconciled_at: str | None = None
    downstream_note: str | None = None
