"""BlueFolder service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.models.requests import BlueFolderJobSummary, CommandResult, PartsCommentRecord, PartsLifecycleSnapshot


@dataclass(slots=True)
class BlueFolderService:
    """Service wrapper around BlueFolder-related operations."""

    adapter: BlueFolderAdapter

    async def get_job_summary(self, reference: str) -> BlueFolderJobSummary:
        """Delegate job-summary lookup to the adapter layer."""
        return await self.adapter.get_job_summary(reference)

    async def get_parts_brief(self, sr_id: int) -> CommandResult:
        """Return a BlueFolder-native parts summary for a service request."""
        summary = await self.adapter.get_job_summary(f"SR-{sr_id}")
        if not summary.available:
            return CommandResult(
                message="\n".join(
                    [
                        f"Parts brief `{sr_id}`",
                        f"BlueFolder: `{summary.integration_status}`",
                        f"Detail: {summary.message}",
                    ]
                )
            )

        lines = [
            f"SR `{summary.service_request_id or sr_id}`",
            f"Subject: {summary.subject or 'Unlabeled Service Request'}",
            f"Customer: {summary.customer_name or 'n/a'}",
            f"Address: {self._format_address(summary) or 'n/a'}",
        ]
        snapshot = await self.get_parts_snapshot(sr_id)
        if snapshot is None:
            lines.append("No recent parts-related comments found.")
            return CommandResult(message="\n".join(lines))

        lines.append(f"Parts stage: `{snapshot.stage_label}`")
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
            lines.append(f"BlueFolder: `{summary.integration_status}`")
            lines.append(f"Detail: {summary.message}")
            return CommandResult(message="\n".join(lines))

        if snapshot is None:
            lines.append("Parts stage: `No Recent Parts Context`")
            lines.append("Recommended next action: Review the SR in BlueFolder and confirm whether parts work is pending.")
            return CommandResult(message="\n".join(lines))

        lines.append(f"Parts stage: `{snapshot.stage_label}`")
        if snapshot.latest_status_text:
            lines.append(f"Latest status detail: {snapshot.latest_status_text[:220]}")
        elif snapshot.latest_issue_text:
            lines.append(f"Latest issue detail: {snapshot.latest_issue_text[:220]}")
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
