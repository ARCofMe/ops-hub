"""BlueFolder service facade."""

from __future__ import annotations

from dataclasses import dataclass

from ops_hub.integrations.bluefolder_adapter import BlueFolderAdapter
from ops_hub.models.requests import BlueFolderJobSummary, CommandResult


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
        comments = await self.adapter.get_recent_parts_comments(sr_id, limit=3)
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
        if comments:
            latest = comments[0]
            lines.append(
                f"Latest parts note: `{latest.date_created or 'unknown'}` by `{latest.author or 'Unknown'}`"
            )
            lines.append(f"Latest text: {latest.text[:220]}")
        else:
            lines.append("No recent parts-related comments found.")
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
    ) -> CommandResult:
        """Add a standardized BlueFolder parts-status update comment."""
        result = await self.adapter.add_parts_update_comment(
            sr_id,
            update_type=update_type,
            details=details,
            requested_by_user_id=requested_by_user_id,
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
