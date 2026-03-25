"""Photo ingest service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.core.config import Settings
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.models.requests import (
    CommandResult,
    PhotoReminderEvaluation,
    PhotoAttachmentPayload,
    PhotoIngestMessage,
    PhotoIngestResult,
)
from ops_hub.services.bluefolder import BlueFolderService
from ops_hub.services.photo_feature_flags import PhotoFeatureFlagsService
from ops_hub.services.notifications import NotificationService
from ops_hub.services.operator_directory import TechnicianDirectoryService


@dataclass(slots=True)
class PhotoIngestService:
    """Photo ingest and compliance service facade."""

    settings: Settings
    adapter: PhotoIngestAdapter
    feature_flags: PhotoFeatureFlagsService
    bluefolder_service: BlueFolderService | None = None
    technician_directory_service: TechnicianDirectoryService | None = None
    notifications: NotificationService | None = None

    async def status(self) -> dict[str, str]:
        """Return placeholder photo-ingest status."""
        status = await self.adapter.healthcheck()
        status["features"] = ", ".join(self.feature_flags.status_lines())
        return status

    def should_process_channel(self, channel_id: int) -> bool:
        """Return whether the message channel should be handled by the listener."""
        configured_channel_id = self.settings.photo_ingest_channel_id
        return configured_channel_id is not None and channel_id == configured_channel_id

    async def handle_message(self, message: PhotoIngestMessage) -> PhotoIngestResult:
        """Handle a message routed from the Discord listener layer."""
        # TODO: Add message-to-ingest translation and compliance workflow wiring.
        if not self.should_process_channel(message.channel_id):
            return PhotoIngestResult(
                handled=False,
                status="ignored_channel",
                message="Message is not in the configured photo ingest channel.",
            )
        return await self.adapter.ingest_message(message)

    async def attach_model_serial_photo(
        self,
        sr_id: int,
        *,
        photo: PhotoAttachmentPayload,
        requested_by_user_id: int,
    ) -> CommandResult:
        """Attach a compressed model/serial photo to a BlueFolder service request."""
        if not self.feature_flags.is_enabled("mdlsn_upload"):
            return CommandResult(message="Model/serial photo upload is currently disabled.")
        result = await self.adapter.attach_photo_to_service_request(
            sr_id,
            photo=photo,
            uploaded_by_user_id=requested_by_user_id,
            label="MDLSN",
        )
        return CommandResult(message=result.message)

    async def archive_job_photos(
        self,
        sr_id: int,
        *,
        photos: list[PhotoAttachmentPayload],
        requested_by_user_id: int,
        sr_subject: str | None = None,
    ) -> CommandResult:
        """Send a batch of compressed job photos to the configured archive mailbox."""
        if not self.feature_flags.is_enabled("photo_archive_handoff"):
            return CommandResult(message="Photo archive handoff is currently disabled.")
        result = await self.adapter.archive_photos_via_email(
            sr_id,
            photos=photos,
            uploaded_by_user_id=requested_by_user_id,
            sr_subject=sr_subject,
        )
        return CommandResult(message=result.message)

    async def get_photo_status(self, sr_id: int) -> CommandResult:
        """Return a mailbox-backed photo compliance summary for a service request."""
        if not self.feature_flags.is_enabled("photo_mailbox_scan"):
            return CommandResult(message="Photo mailbox scan is currently disabled.")

        summary = await self.adapter.get_photo_compliance_summary(sr_id)
        lines = [f"**Photo Status SR-{sr_id}**", "", f"Mailbox status: `{summary.mailbox_status}`", summary.message]
        if summary.found_tags or summary.missing_tags:
            lines.extend(
                [
                    "",
                    f"Found required tags: {', '.join(f'`{tag}`' for tag in summary.found_tags) if summary.found_tags else 'none'}",
                    f"Missing required tags: {', '.join(f'`{tag}`' for tag in summary.missing_tags) if summary.missing_tags else 'none'}",
                ]
            )
        if summary.matched_records:
            lines.extend(["", "**Recent Matches**"])
            for idx, record in enumerate(summary.matched_records[:5], start=1):
                lines.append(
                    f"{idx}. `{record.received_at or 'unknown'}` from `{record.from_email or 'unknown'}` "
                    f"with `{record.attachment_count}` photo(s)"
                )
                lines.append(record.subject)
                if record.attachment_names:
                    lines.append("Attachments: " + ", ".join(f"`{name}`" for name in record.attachment_names[:6]))
        return CommandResult(message="\n".join(lines))

    async def evaluate_photo_reminder(
        self,
        sr_id: int,
        *,
        status_override: str | None = None,
        send_notice: bool = False,
    ) -> CommandResult:
        """Evaluate whether the assigned technician should be reminded about missing photos."""
        summary = None
        if self.bluefolder_service is not None:
            summary = await self.bluefolder_service.get_job_summary(f"SR-{sr_id}")
        service_request_status = status_override or (summary.service_request_status if summary is not None else None)
        matched_required_status = self._matches_required_status(service_request_status)
        compliance = await self.adapter.get_photo_compliance_summary(sr_id)
        missing_photos = compliance.total_photos <= 0 or bool(compliance.missing_tags)
        technician_discord_user_id = await self._resolve_assigned_technician(sr_id)

        evaluation = PhotoReminderEvaluation(
            sr_id=sr_id,
            service_request_status=service_request_status,
            matched_required_status=matched_required_status,
            missing_photos=missing_photos,
            technician_discord_user_id=technician_discord_user_id,
            should_notify=matched_required_status and missing_photos and technician_discord_user_id is not None,
            reason=self._build_reminder_reason(
                service_request_status=service_request_status,
                matched_required_status=matched_required_status,
                missing_photos=missing_photos,
                technician_discord_user_id=technician_discord_user_id,
            ),
        )

        notice_sent = False
        if send_notice and evaluation.should_notify and self.notifications is not None:
            mention = self._technician_mention(technician_discord_user_id)
            await self.notifications.send_notice(
                topic="photo.missing",
                message=(
                    f"{mention} SR-{sr_id} is in a photo-required status "
                    f"(`{service_request_status or 'unknown'}`) and no archived photos were found."
                ),
            )
            notice_sent = True

        lines = [
            f"**Photo Reminder Check SR-{sr_id}**",
            "",
            f"Service request status: `{service_request_status or 'unknown'}`",
            f"Photo-required status match: `{'yes' if matched_required_status else 'no'}`",
            f"Photos present: `{'yes' if not missing_photos else 'no'}`",
            f"Assigned technician: {self._technician_mention(technician_discord_user_id) if technician_discord_user_id else 'not resolved'}",
            f"Should notify: `{'yes' if evaluation.should_notify else 'no'}`",
            f"Reason: {evaluation.reason}",
        ]
        if notice_sent:
            lines.extend(["", "Reminder notice sent."])
        return CommandResult(message="\n".join(lines))

    def _matches_required_status(self, service_request_status: str | None) -> bool:
        """Return whether the SR status is one that requires photos."""
        if not service_request_status:
            return False
        configured = {status.strip().casefold() for status in self.settings.photo_required_sr_statuses if status.strip()}
        if not configured:
            return False
        return service_request_status.strip().casefold() in configured

    async def _resolve_assigned_technician(self, sr_id: int) -> int | None:
        """Resolve the Discord technician for today's assigned SR when possible."""
        if self.bluefolder_service is None or self.technician_directory_service is None:
            return None

        reverse_mappings = self.technician_directory_service.reverse_mappings()
        for bluefolder_user_id, discord_user_id in reverse_mappings.items():
            assignments = await self.bluefolder_service.get_assignments_for_user_today(bluefolder_user_id)
            for assignment in assignments:
                assignment_id = str(assignment.get("id") or "").strip()
                if assignment_id == str(sr_id):
                    return discord_user_id
        return None

    def _build_reminder_reason(
        self,
        *,
        service_request_status: str | None,
        matched_required_status: bool,
        missing_photos: bool,
        technician_discord_user_id: int | None,
    ) -> str:
        """Render a concise explanation for the current reminder decision."""
        if not service_request_status:
            return "No service request status was available for evaluation."
        if not matched_required_status:
            return "Current service request status is not in the configured photo-required list."
        if not missing_photos:
            return "Archived photos already satisfy the current required-tag policy for this service request."
        if technician_discord_user_id is None:
            return "No mapped technician assignment could be resolved for this service request today."
        return "The SR is in a photo-required status, no archived photos were found, and a technician is mapped."

    @staticmethod
    def _technician_mention(discord_user_id: int | None) -> str | None:
        """Render a Discord mention for a resolved technician."""
        if discord_user_id is None:
            return None
        return f"<@{discord_user_id}>"
