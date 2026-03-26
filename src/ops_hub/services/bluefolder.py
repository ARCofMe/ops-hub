"""BlueFolder service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.models.requests import (
    BlueFolderJobSummary,
    CommandResult,
    CustomerContactSummary,
    PartsCommentRecord,
    PartsLifecycleSnapshot,
)
from ops_hub.services.notifications import NotificationService


@dataclass(slots=True)
class BlueFolderService:
    """Service wrapper around BlueFolder-related operations."""

    adapter: BlueFolderAdapter
    notifications: NotificationService | None = None

    async def get_job_summary(self, reference: str) -> BlueFolderJobSummary:
        """Delegate job-summary lookup to the adapter layer."""
        return await self.adapter.get_job_summary(reference)

    async def get_active_user_directory(self) -> dict[int, str]:
        """Return active BlueFolder users keyed by user id."""
        return await self.adapter.get_active_user_directory()

    async def get_user_name(self, user_id: int) -> str | None:
        """Return a readable BlueFolder user name when available."""
        return await self.adapter.get_user_name(user_id)

    async def get_assignments_for_user_today(self, user_id: int) -> list[dict[str, str | bool | None]]:
        """Return today's scheduled assignments directly from BlueFolder."""
        return await self.adapter.get_assignments_for_user_today(user_id)

    async def get_parts_brief(self, sr_id: int) -> CommandResult:
        """Return a BlueFolder-native parts summary for a service request."""
        summary = await self.adapter.get_job_summary(f"SR-{sr_id}")
        snapshot = await self.get_parts_snapshot(sr_id)
        if not summary.available:
            lines = [
                f"**Parts Brief SR-{sr_id}**",
                "",
                "**BlueFolder**",
                f"Status: `{summary.integration_status}`",
                f"Detail: {summary.message}",
            ]
            if snapshot is None:
                return CommandResult(message="\n".join(lines))

            lines.extend(
                [
                    "",
                    "**Parts Status**",
                    f"Parts stage: `{snapshot.stage_label}`",
                ]
            )
            if snapshot.latest_status_at or snapshot.latest_status_author:
                lines.append(
                    "Latest status note: "
                    f"`{snapshot.latest_status_at or 'unknown'}` by `{snapshot.latest_status_author or 'Unknown'}`"
                )
            if snapshot.latest_status_text:
                lines.append(f"Status detail: {snapshot.latest_status_text[:220]}")
            if snapshot.latest_issue_type:
                lines.append(
                    "Latest issue: "
                    f"`{snapshot.latest_issue_type.replace('_', '-')}` at "
                    f"`{snapshot.latest_issue_at or 'unknown'}` by `{snapshot.latest_issue_author or 'Unknown'}`"
                )
            if snapshot.latest_issue_text:
                lines.append(f"Issue detail: {snapshot.latest_issue_text[:220]}")
            lines.append("")
            lines.append(f"Recommended next action: {self.recommend_next_action(snapshot)}")
            return CommandResult(message="\n".join(lines))

        lines = [
            f"**Parts Brief SR-{summary.service_request_id or sr_id}**",
            f"SR: `{summary.service_request_id or sr_id}`",
            "",
            "**Service Request**",
            f"Subject: {summary.subject or 'Unlabeled Service Request'}",
            f"Customer: {summary.customer_name or 'n/a'}",
            f"Address: {self._format_address(summary) or 'n/a'}",
        ]
        if snapshot is None:
            lines.extend(
                [
                    "",
                    "**Parts Status**",
                    "No recent parts-related comments found.",
                ]
            )
            return CommandResult(message="\n".join(lines))

        lines.extend(
            [
                "",
                "**Parts Status**",
                f"Parts stage: `{snapshot.stage_label}`",
            ]
        )
        if snapshot.latest_status_at or snapshot.latest_status_author:
            lines.append(
                "Latest status note: "
                f"`{snapshot.latest_status_at or 'unknown'}` by `{snapshot.latest_status_author or 'Unknown'}`"
            )
        if snapshot.latest_status_text:
            lines.append(f"Status detail: {snapshot.latest_status_text[:220]}")
        if snapshot.latest_issue_type:
            lines.append(
                "Latest issue: "
                f"`{snapshot.latest_issue_type.replace('_', '-')}` at "
                f"`{snapshot.latest_issue_at or 'unknown'}` by `{snapshot.latest_issue_author or 'Unknown'}`"
            )
        if snapshot.latest_issue_text:
            lines.append(f"Issue detail: {snapshot.latest_issue_text[:220]}")
        lines.append("")
        lines.append(f"Recommended next action: {self.recommend_next_action(snapshot)}")
        return CommandResult(message="\n".join(lines))

    async def get_parts_notes(self, sr_id: int) -> CommandResult:
        """Return recent parts-related BlueFolder comments for a service request."""
        comments = await self.adapter.get_recent_parts_comments(sr_id, limit=6)
        if not comments:
            return CommandResult(message=f"No recent parts-related comments found for `{sr_id}`.")

        blocks = ["Parts notes"]
        for idx, comment in enumerate(comments, start=1):
            blocks.append(f"{idx}. `{comment.date_created or 'unknown'}` by `{comment.author or 'Unknown'}`")
            blocks.append(comment.text)
        return CommandResult(message="\n".join(blocks))

    async def get_parts_snapshot(self, sr_id: int) -> PartsLifecycleSnapshot | None:
        """Return a normalized parts lifecycle snapshot when recent parts comments exist."""
        comments = await self.adapter.get_recent_parts_comments(sr_id, limit=6)
        if not comments:
            return None
        return self._build_parts_lifecycle_snapshot(comments)

    async def get_parts_next_action(self, sr_id: int) -> CommandResult:
        """Return a dispatcher-friendly next-action recommendation for an SR."""
        summary = await self.adapter.get_job_summary(f"SR-{sr_id}")
        snapshot = await self.get_parts_snapshot(sr_id)

        lines = [f"Dispatch next `{sr_id}`"]
        if summary.available:
            lines.append(f"Subject: {summary.subject or 'Unlabeled Service Request'}")
        else:
            lines.extend(
                [
                    "",
                    "**BlueFolder**",
                    f"Status: `{summary.integration_status}`",
                ]
            )
            lines.append(f"Detail: {summary.message}")
            return CommandResult(message="\n".join(lines))

        if snapshot is None:
            lines.extend(
                [
                    "",
                    "**Parts Status**",
                    "Parts stage: `No Recent Parts Context`",
                ]
            )
            lines.append("Recommended next action: Review the SR in BlueFolder and confirm whether parts work is pending.")
            return CommandResult(message="\n".join(lines))

        lines.extend(
            [
                "",
                "**Parts Status**",
                f"Parts stage: `{snapshot.stage_label}`",
            ]
        )
        if snapshot.latest_status_text:
            lines.append(f"Latest status detail: {snapshot.latest_status_text[:220]}")
        elif snapshot.latest_issue_text:
            lines.append(f"Latest issue detail: {snapshot.latest_issue_text[:220]}")
        lines.append("")
        lines.append(f"Recommended next action: {self.recommend_next_action(snapshot)}")
        return CommandResult(message="\n".join(lines))

    async def log_parts_issue(
        self,
        sr_id: int,
        *,
        issue_type: str,
        details: str,
        requested_by_user_id: int,
    ) -> CommandResult:
        """Add a standardized BlueFolder parts comment for a technician-facing issue."""
        result = await self.adapter.add_parts_comment(
            sr_id,
            issue_type=issue_type,
            details=details,
            requested_by_user_id=requested_by_user_id,
        )
        if not result.get("ok"):
            return CommandResult(
                message=(
                    f"Could not log {issue_type.replace('_', '-')} issue for `{sr_id}`: "
                    f"{result.get('error') or 'unknown error'}"
                )
            )
        return CommandResult(
            message="\n".join(
                [
                    f"Logged {issue_type.replace('_', '-')} issue for `{sr_id}`",
                    f"Logged at: `{result.get('logged_at') or 'unknown'}`",
                    f"BlueFolder note: {result.get('note_text') or ''}",
                ]
            )
        )

    async def log_parts_update(
        self,
        sr_id: int,
        *,
        update_type: str,
        details: str,
        requested_by_user_id: int,
        metadata: dict[str, str] | None = None,
    ) -> CommandResult:
        """Add a standardized BlueFolder parts-status update comment."""
        result = await self.adapter.add_parts_update_comment(
            sr_id,
            update_type=update_type,
            details=details,
            requested_by_user_id=requested_by_user_id,
            metadata=metadata,
        )
        if not result.get("ok"):
            return CommandResult(
                message=(
                    f"Could not log {update_type.replace('_', '-')} update for `{sr_id}`: "
                    f"{result.get('error') or 'unknown error'}"
                )
            )
        return CommandResult(
            message="\n".join(
                [
                    f"Logged {update_type.replace('_', '-')} update for `{sr_id}`",
                    f"Logged at: `{result.get('logged_at') or 'unknown'}`",
                    f"BlueFolder note: {result.get('note_text') or ''}",
                ]
            )
        )

    async def log_contact_issue(
        self,
        sr_id: int,
        *,
        issue_type: str,
        details: str | None,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        notify_dispatch: bool = True,
    ) -> CommandResult:
        """Add a standardized BlueFolder contact issue comment and optionally notify dispatch."""
        return await self.log_field_event(
            sr_id,
            event_type=issue_type,
            requested_by_user_id=requested_by_user_id,
            requested_by_label=requested_by_label,
            details=details,
            notify_dispatch=notify_dispatch,
        )

    async def log_route_update(
        self,
        sr_id: int,
        *,
        update_type: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        minutes: int | None = None,
        notify_dispatch: bool = False,
    ) -> CommandResult:
        """Add a standardized BlueFolder route-status comment and optionally notify dispatch."""
        return await self.log_field_event(
            sr_id,
            event_type=update_type,
            requested_by_user_id=requested_by_user_id,
            requested_by_label=requested_by_label,
            minutes=minutes,
            notify_dispatch=notify_dispatch,
        )

    async def log_field_event(
        self,
        sr_id: int,
        *,
        event_type: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        details: str | None = None,
        minutes: int | None = None,
        notify_dispatch: bool = False,
    ) -> CommandResult:
        """Add a standardized field-workflow comment and optionally notify dispatch."""
        result = await self.adapter.add_field_event_comment(
            sr_id,
            event_type=event_type,
            requested_by_user_id=requested_by_user_id,
            requested_by_label=requested_by_label,
            details=details,
            minutes=minutes,
        )
        if not result.get("ok"):
            return CommandResult(
                message=(
                    f"Could not log {event_type.replace('_', '-')} for `{sr_id}`: "
                    f"{result.get('error') or 'unknown error'}"
                )
            )
        if notify_dispatch and self.notifications is not None:
            await self.notifications.send_notice(
                topic=self._field_event_topic(event_type),
                message=f"SR-{sr_id} {event_type.replace('_', '-')} logged. {result.get('note_text') or ''}",
            )
        return CommandResult(
            message="\n".join(
                [
                    f"Logged {event_type.replace('_', '-')} for `{sr_id}`",
                    f"Logged at: `{result.get('logged_at') or 'unknown'}`",
                    f"BlueFolder note: {result.get('note_text') or ''}",
                ]
            )
        )

    async def get_customer_snapshot(self, sr_id: int) -> CommandResult:
        """Return a concise customer and location snapshot for field use."""
        summary = await self.adapter.get_job_summary(f"SR-{sr_id}")
        if not summary.available:
            return CommandResult(
                message="\n".join(
                    [
                        f"**Customer SR-{sr_id}**",
                        "",
                        "**BlueFolder**",
                        f"Status: `{summary.integration_status}`",
                        f"Detail: {summary.message}",
                    ]
                )
            )

        lines = [
            f"**Customer SR-{summary.service_request_id or sr_id}**",
            f"Subject: {summary.subject or 'Unlabeled Service Request'}",
            f"Customer: {summary.customer_name or 'n/a'}",
        ]
        if summary.customer_phone:
            lines.append(f"Phone: {summary.customer_phone}")
        if summary.service_request_status:
            lines.append(f"Status: `{summary.service_request_status}`")
        if address := self._format_address(summary):
            lines.append(f"Address: {address}")
        if summary.customer_contacts:
            lines.extend(["", "**Contacts**"])
            for contact in summary.customer_contacts[:3]:
                lines.append(self._format_customer_contact(contact))
        if summary.customer_id or summary.customer_location_id:
            lines.extend(["", "**BlueFolder**"])
            if summary.customer_id:
                lines.append(f"Customer ID: `{summary.customer_id}`")
            if summary.customer_location_id:
                lines.append(f"Location ID: `{summary.customer_location_id}`")
        return CommandResult(message="\n".join(lines))

    def _format_address(self, summary: BlueFolderJobSummary) -> str:
        """Format a readable address from the BlueFolder job summary."""
        return ", ".join(
            part
            for part in [
                summary.address,
                " ".join(
                    value for value in [summary.city, summary.state, summary.postal_code] if value
                ).strip(),
            ]
            if part
        )

    def _format_customer_contact(self, contact: CustomerContactSummary) -> str:
        """Render a customer contact line for Discord output."""
        bits = [contact.name]
        if contact.title:
            bits.append(contact.title)
        if contact.phone:
            bits.append(contact.phone)
        if contact.email:
            bits.append(contact.email)
        prefix = "Primary" if contact.is_primary else "Contact"
        return f"{prefix}: {' | '.join(bits)}"

    def recommend_next_action(self, snapshot: PartsLifecycleSnapshot) -> str:
        """Return a plain-language recommended next action for the current parts stage."""
        if snapshot.stage == "issue_reported":
            return "Parts should review the issue note, confirm the part path, and post an ordered or ETA update."
        if snapshot.stage == "part_ordered":
            return "Monitor vendor progress and post ETA or tracking information when available."
        if snapshot.stage == "part_eta":
            return "Keep dispatch aware of the ETA and follow up if the arrival window changes."
        if snapshot.stage == "part_tracking":
            return "Track shipment progress and prepare dispatch for receipt or scheduling follow-up."
        if snapshot.stage == "part_received":
            return "Confirm install readiness with the tech and prepare customer scheduling follow-up."
        if snapshot.stage == "part_ready":
            return "Dispatch should contact the customer and move the SR toward scheduling."
        return "Review the latest BlueFolder parts notes and determine the next update needed."

    def _field_event_topic(self, event_type: str) -> str:
        """Resolve the dispatch notice topic for a field event."""
        if event_type in {"eta", "enroute"}:
            return "dispatch.route_update"
        if event_type in {"no_answer", "not_home"}:
            return "dispatch.contact_issue"
        return "dispatch.field_update"

    def _build_parts_lifecycle_snapshot(self, comments: list[PartsCommentRecord]) -> PartsLifecycleSnapshot:
        """Derive a normalized parts stage and relevant details from recent comments."""
        latest_issue: tuple[str, PartsCommentRecord] | None = None
        latest_status: tuple[str, str, PartsCommentRecord] | None = None
        status_markers = [
            ("part_ready", "Ready for Scheduling", ("part ready for scheduling", "ready for scheduling")),
            ("part_received", "Received", ("part received", "received")),
            ("part_tracking", "Tracking Posted", ("part tracking update", "tracking update", "tracking #", "tracking number")),
            ("part_eta", "ETA Posted", ("part eta update", "eta update", "eta ")),
            ("part_ordered", "Ordered", ("part ordered", "ordered")),
        ]

        for comment in comments:
            text = comment.text.casefold()
            if latest_issue is None:
                if "missing part reported" in text:
                    latest_issue = ("missing_part", comment)
                elif "damaged part reported" in text:
                    latest_issue = ("damaged_part", comment)
            if latest_status is None:
                for stage, label, markers in status_markers:
                    if any(marker in text for marker in markers):
                        latest_status = (stage, label, comment)
                        break
            if latest_issue and latest_status:
                break

        if latest_status is not None:
            stage, label, status_comment = latest_status
            return PartsLifecycleSnapshot(
                stage=stage,
                stage_label=label,
                latest_status_text=status_comment.text,
                latest_status_author=status_comment.author,
                latest_status_at=status_comment.date_created,
                latest_issue_type=latest_issue[0] if latest_issue else None,
                latest_issue_text=latest_issue[1].text if latest_issue else None,
                latest_issue_author=latest_issue[1].author if latest_issue else None,
                latest_issue_at=latest_issue[1].date_created if latest_issue else None,
            )

        if latest_issue is not None:
            issue_type, issue_comment = latest_issue
            return PartsLifecycleSnapshot(
                stage="issue_reported",
                stage_label="Issue Reported",
                latest_status_text=issue_comment.text,
                latest_status_author=issue_comment.author,
                latest_status_at=issue_comment.date_created,
                latest_issue_type=issue_type,
                latest_issue_text=issue_comment.text,
                latest_issue_author=issue_comment.author,
                latest_issue_at=issue_comment.date_created,
            )

        latest_comment = comments[0]
        return PartsLifecycleSnapshot(
            stage="parts_activity",
            stage_label="Parts Activity Logged",
            latest_status_text=latest_comment.text,
            latest_status_author=latest_comment.author,
            latest_status_at=latest_comment.date_created,
        )
