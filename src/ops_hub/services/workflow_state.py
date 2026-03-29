"""Ops Hub workflow-state derivation and event capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ops_hub.models.requests import (
    AttentionItemRecord,
    CommandResult,
    PartRequestRecord,
    PartsCaseRecord,
    PartsLifecycleSnapshot,
    ServiceRequestTimeline,
    ServiceRequestTimelineEntry,
    TechnicianMappingRecord,
    WorkflowEventRecord,
    WorkflowStateSnapshot,
)
from ops_hub.services.workflow_state_store import WorkflowStateStore

if TYPE_CHECKING:
    from ops_hub.services.bluefolder import BlueFolderService
    from ops_hub.services.notifications import NotificationService
    from ops_hub.services.operator_directory import TechnicianDirectoryService
    from ops_hub.services.parts_cannon import PartsCannonService


@dataclass(slots=True)
class WorkflowStateService:
    """Own derived workflow state that should outlive one command invocation."""

    store: WorkflowStateStore
    bluefolder_service: "BlueFolderService"
    parts_cannon_service: "PartsCannonService"
    technician_directory_service: "TechnicianDirectoryService | None" = None
    notification_service: "NotificationService | None" = None
    attention_sla_hours: dict[str, tuple[int, int, int]] = field(
        default_factory=lambda: {
            "issue_reported": (2, 12, 24),
            "part_received": (8, 24, 72),
            "part_ready": (4, 24, 48),
            "requested": (8, 24, 48),
            "ordered": (12, 48, 96),
            "received": (8, 24, 72),
            "no_recent_parts_context": (24, 72, 120),
        }
    )

    def current_snapshot(self) -> WorkflowStateSnapshot:
        """Return the current workflow snapshot."""
        return self.store.load()

    async def run_policy_cycle(self, *, emit_notices: bool = True) -> dict[str, int]:
        """Refresh workflow state and optionally emit deduplicated urgent notices."""
        mappings = self.technician_directory_service.mapping_records() if self.technician_directory_service is not None else []
        _, attention_items = await self.refresh_dispatch_attention(mappings)
        urgent_items = [item for item in attention_items if item.age_bucket == "urgent"]
        notices_sent = 0
        for item in urgent_items:
            if emit_notices and self._was_notified_recently(item_id=item.item_id, hours=6):
                continue
            if emit_notices and self.notification_service is not None:
                await self.notification_service.send_notice(
                    topic=f"dispatch.attention.{item.stage}",
                    message=(
                        f"{item.reference} needs dispatch attention. "
                        f"Stage: {item.stage_label}. "
                        f"Age: {item.age_hours or 0}h ({item.age_bucket}). "
                        f"{item.next_action or ''}".strip()
                    ),
                )
            if emit_notices:
                self.record_event(
                    event_type="attention_notice",
                    source="ops_hub.policy",
                    sr_id=item.sr_id,
                    reference=item.reference,
                    summary=f"Sent urgent attention notice for {item.reference}.",
                    details=item.next_action,
                    metadata={"item_id": item.item_id, "age_bucket": item.age_bucket or ""},
                )
                notices_sent += 1
        return {"attention_items": len(attention_items), "urgent_items": len(urgent_items), "notices_sent": notices_sent}

    async def get_parts_case(self, *, sr_id: int | None = None, reference: str | None = None) -> PartsCaseRecord:
        """Return a current parts-case record for one SR or reference."""
        resolved_reference = reference or (f"SR-{sr_id}" if sr_id is not None else None)
        if resolved_reference is None:
            raise ValueError("sr_id or reference is required")
        resolved_sr_id = sr_id if sr_id is not None else self._reference_sr_id(resolved_reference)
        snapshot = await self.bluefolder_service.get_parts_snapshot(resolved_sr_id) if resolved_sr_id is not None else None
        matching_requests = self._matching_requests(self.parts_cannon_service.request_store.load(), resolved_reference)
        case = self._build_parts_case(
            reference=resolved_reference,
            sr_id=resolved_sr_id,
            snapshot=snapshot,
            matching_requests=matching_requests,
        )

        state = self.store.load()
        remaining_cases = [item for item in state.parts_cases if item.case_id != case.case_id]
        state.parts_cases = sorted([*remaining_cases, case], key=lambda item: (item.reference, item.stage))
        state.updated_at = self._now()
        self.store.save(state)
        return case

    async def describe_parts_case(self, sr_id: int) -> CommandResult:
        """Render a user-facing parts-case summary for one service request."""
        reference = f"SR-{sr_id}"
        case = await self.get_parts_case(sr_id=sr_id)
        summary = await self.bluefolder_service.get_job_summary(reference, include_customer_contacts=False)

        lines = [f"**Parts Case {reference}**"]
        if summary.available:
            lines.append(f"Subject: {summary.subject or 'Unlabeled Service Request'}")
            if summary.customer_name:
                lines.append(f"Customer: {summary.customer_name}")
        lines.extend(
            [
                f"Stage: `{case.stage_label}`",
                f"Case status: `{case.status}`",
            ]
        )
        if case.open_request_ids:
            lines.append("Tracked requests: " + ", ".join(f"`{request_id}`" for request_id in case.open_request_ids))
        if case.assigned_parts_user_id is not None:
            lines.append(f"Assigned parts owner: {self._user_label(case.assigned_parts_user_id)}")
        if case.blocker:
            lines.append(f"Blocker: {case.blocker[:220]}")
        if case.latest_status_text:
            lines.append(f"Latest status: {case.latest_status_text[:220]}")
        if case.latest_issue_text and case.latest_issue_text != case.blocker:
            lines.append(f"Latest issue: {case.latest_issue_text[:220]}")
        if case.next_action:
            lines.extend(["", f"Next action: {case.next_action}"])
        return CommandResult(message="\n".join(lines))

    async def describe_service_request_timeline(self, sr_id: int) -> CommandResult:
        """Render a user-facing timeline for one service request."""
        timeline = await self.build_service_request_timeline(sr_id)
        lines = [f"**Job Timeline SR-{sr_id}**"]
        if not timeline.entries:
            lines.append("No timeline entries are available yet.")
            return CommandResult(message="\n".join(lines))

        for index, entry in enumerate(timeline.entries[:10], start=1):
            lines.append("")
            lines.append(f"{index}. `{entry.occurred_at or 'unknown'}` `{entry.source}` `{entry.event_type}`")
            lines.append(entry.summary)
            if entry.actor_label:
                lines.append(f"Actor: {entry.actor_label}")
            if entry.details:
                lines.append(f"Detail: {entry.details[:220]}")
        if len(timeline.entries) > 10:
            lines.extend(["", f"...and {len(timeline.entries) - 10} more timeline entrie(s)"])
        return CommandResult(message="\n".join(lines))

    def record_event(
        self,
        *,
        event_type: str,
        source: str,
        summary: str,
        sr_id: int | None = None,
        reference: str | None = None,
        actor_user_id: int | None = None,
        actor_label: str | None = None,
        details: str | None = None,
        metadata: dict[str, str] | None = None,
        occurred_at: str | None = None,
    ) -> WorkflowEventRecord:
        """Append one event into the persisted workflow state."""
        snapshot = self.store.load()
        timestamp = occurred_at or self._now()
        event = WorkflowEventRecord(
            event_id=self._event_id(source=source, event_type=event_type, sr_id=sr_id, timestamp=timestamp),
            event_type=event_type,
            source=source,
            occurred_at=timestamp,
            summary=summary,
            sr_id=sr_id,
            reference=reference or (f"SR-{sr_id}" if sr_id is not None else None),
            actor_user_id=actor_user_id,
            actor_label=actor_label,
            details=details,
            metadata=dict(metadata or {}),
        )
        snapshot.events.append(event)
        snapshot.updated_at = self._now()
        self.store.save(snapshot)
        return event

    async def refresh_dispatch_attention(
        self,
        mappings: list[TechnicianMappingRecord],
        *,
        stage_filter: str | None = None,
        technician_bluefolder_user_id: int | None = None,
        age_bucket: str | None = None,
        owner_discord_user_id: int | None = None,
    ) -> tuple[int, list[AttentionItemRecord]]:
        """Derive and persist current dispatch attention items."""
        allowed_stages = {
            "issue_reported": "Issue Reported",
            "part_received": "Received",
            "part_ready": "Ready for Scheduling",
        }
        normalized_stage_filter = None if stage_filter is None else stage_filter.strip().lower().replace(" ", "_")

        if technician_bluefolder_user_id is not None:
            mappings = [record for record in mappings if record.bluefolder_user_id == technician_bluefolder_user_id]

        scanned_jobs = 0
        attention_items: list[AttentionItemRecord] = []
        parts_cases: dict[str, PartsCaseRecord] = {}
        current_snapshot = self.store.load()
        previous_items = {item.item_id: item for item in current_snapshot.attention_items}
        parts_records = self.parts_cannon_service.request_store.load()

        for record in mappings:
            assignments = await self.bluefolder_service.get_assignments_for_user_today(record.bluefolder_user_id)
            for assignment in assignments[:10]:
                sr_id = self._parse_sr_id(assignment.get("serviceRequestId"))
                if sr_id is None:
                    continue
                scanned_jobs += 1
                reference = f"SR-{sr_id}"
                snapshot = await self.bluefolder_service.get_parts_snapshot(sr_id)
                matching_requests = self._matching_requests(parts_records, reference)
                parts_case = self._build_parts_case(
                    reference=reference,
                    sr_id=sr_id,
                    snapshot=snapshot,
                    matching_requests=matching_requests,
                )
                parts_cases[parts_case.case_id] = parts_case
                if snapshot is None or snapshot.stage not in allowed_stages:
                    continue
                if normalized_stage_filter is not None and snapshot.stage != normalized_stage_filter:
                    continue

                location = " ".join(part for part in [assignment.get("city"), assignment.get("state")] if part).strip()
                route_label = str(assignment.get("routeLabel") or assignment.get("window") or assignment.get("timeWindow") or "").strip() or None
                summary = str(assignment.get("subject") or "Unlabeled Service Request")
                item_id = f"dispatch:{reference}:{snapshot.stage}"
                previous = previous_items.get(item_id)
                first_seen_at = (
                    previous.first_seen_at
                    if previous is not None and previous.first_seen_at
                    else snapshot.latest_issue_at
                    or snapshot.latest_status_at
                    or self._now()
                )
                derived_age_hours = self._age_hours(first_seen_at)
                derived_age_bucket = self._age_bucket_for_stage(snapshot.stage, derived_age_hours)
                if age_bucket is not None and derived_age_bucket != age_bucket:
                    continue
                if owner_discord_user_id is not None and record.discord_user_id != owner_discord_user_id:
                    continue
                attention_items.append(
                    AttentionItemRecord(
                        item_id=item_id,
                        sr_id=sr_id,
                        reference=reference,
                        category="dispatch",
                        status="open",
                        stage=snapshot.stage,
                        stage_label=snapshot.stage_label,
                        summary=summary,
                        details=snapshot.latest_status_text or snapshot.latest_issue_text,
                        location=location or None,
                        route_label=route_label,
                        owner_discord_user_id=record.discord_user_id,
                        owner_bluefolder_user_id=record.bluefolder_user_id,
                        next_action=self.bluefolder_service.recommend_next_action(snapshot),
                        first_seen_at=first_seen_at,
                        last_seen_at=self._now(),
                        age_hours=derived_age_hours,
                        age_bucket=derived_age_bucket,
                    )
                )

        for reference in {record.reference for record in parts_records}:
            sr_id = self._reference_sr_id(reference)
            matching_requests = self._matching_requests(parts_records, reference)
            snapshot = await self.bluefolder_service.get_parts_snapshot(sr_id) if sr_id is not None else None
            parts_case = self._build_parts_case(
                reference=reference,
                sr_id=sr_id,
                snapshot=snapshot,
                matching_requests=matching_requests,
            )
            parts_cases[parts_case.case_id] = parts_case

        updated_snapshot = WorkflowStateSnapshot(
            updated_at=self._now(),
            attention_items=attention_items,
            parts_cases=sorted(parts_cases.values(), key=lambda item: (item.reference, item.stage)),
            events=current_snapshot.events,
        )
        self.store.save(updated_snapshot)
        return scanned_jobs, attention_items

    async def build_service_request_timeline(self, sr_id: int) -> ServiceRequestTimeline:
        """Build a merged SR timeline from Ops Hub events and known parts state."""
        reference = f"SR-{sr_id}"
        entries: list[ServiceRequestTimelineEntry] = []
        snapshot = self.store.load()

        for event in snapshot.events:
            if event.sr_id == sr_id or event.reference == reference:
                entries.append(
                    ServiceRequestTimelineEntry(
                        occurred_at=event.occurred_at,
                        source=event.source,
                        event_type=event.event_type,
                        summary=event.summary,
                        details=event.details,
                        actor_label=event.actor_label,
                    )
                )

        for record in self._matching_requests(self.parts_cannon_service.request_store.load(), reference):
            entries.append(
                ServiceRequestTimelineEntry(
                    occurred_at=record.updated_at,
                    source="ops_hub.parts_queue",
                    event_type=f"parts_request_{record.status}",
                    summary=f"Tracked parts request {record.request_id} is {record.status}.",
                    details=record.downstream_note or record.description,
                    actor_label=self._user_label(record.assigned_parts_user_id or record.requested_by_user_id),
                )
            )

        parts_snapshot = await self.bluefolder_service.get_parts_snapshot(sr_id)
        if parts_snapshot is not None:
            if parts_snapshot.latest_status_text:
                entries.append(
                    ServiceRequestTimelineEntry(
                        occurred_at=parts_snapshot.latest_status_at or "",
                        source="bluefolder.parts",
                        event_type=parts_snapshot.stage,
                        summary=f"Parts status moved to {parts_snapshot.stage_label}.",
                        details=parts_snapshot.latest_status_text,
                        actor_label=parts_snapshot.latest_status_author,
                    )
                )
            if parts_snapshot.latest_issue_text:
                entries.append(
                    ServiceRequestTimelineEntry(
                        occurred_at=parts_snapshot.latest_issue_at or "",
                        source="bluefolder.parts",
                        event_type=parts_snapshot.latest_issue_type or "issue_reported",
                        summary="Parts issue reported.",
                        details=parts_snapshot.latest_issue_text,
                        actor_label=parts_snapshot.latest_issue_author,
                    )
                )

        entries.sort(key=lambda item: item.occurred_at or "", reverse=True)
        return ServiceRequestTimeline(sr_id=sr_id, reference=reference, entries=entries)

    def _build_parts_case(
        self,
        *,
        reference: str,
        sr_id: int | None,
        snapshot: PartsLifecycleSnapshot | None,
        matching_requests: list[PartRequestRecord],
    ) -> PartsCaseRecord:
        """Build a derived parts-case record from current known state."""
        open_requests = [record.request_id for record in matching_requests if record.status not in {"resolved", "cancelled"}]
        latest_request = max(matching_requests, key=lambda item: item.updated_at, default=None)
        base_time = None
        if snapshot is None and latest_request is None:
            stage = "no_recent_parts_context"
            stage_label = "No Recent Parts Context"
            blocker = None
            next_action = "Review the SR and confirm whether parts work is pending."
            latest_status_text = None
            latest_issue_text = None
            base_time = self._now()
        else:
            stage = snapshot.stage if snapshot is not None else latest_request.status
            stage_label = snapshot.stage_label if snapshot is not None else latest_request.status.title()
            blocker = snapshot.latest_issue_text if snapshot is not None else None
            next_action = (
                self.bluefolder_service.recommend_next_action(snapshot)
                if snapshot is not None
                else "Review the tracked request and confirm the next parts step."
            )
            latest_status_text = snapshot.latest_status_text if snapshot is not None else None
            latest_issue_text = snapshot.latest_issue_text if snapshot is not None else None
            base_time = (
                (snapshot.latest_issue_at if snapshot is not None else None)
                or (snapshot.latest_status_at if snapshot is not None else None)
                or (latest_request.updated_at if latest_request is not None else None)
                or self._now()
            )
        derived_age_hours = self._age_hours(base_time)
        return PartsCaseRecord(
            case_id=reference,
            reference=reference,
            sr_id=sr_id,
            stage=stage,
            stage_label=stage_label,
            status="open" if open_requests else "inactive",
            open_request_ids=open_requests,
            assigned_parts_user_id=latest_request.assigned_parts_user_id if latest_request is not None else None,
            requested_by_user_id=latest_request.requested_by_user_id if latest_request is not None else None,
            technician_bluefolder_user_id=latest_request.technician_bluefolder_user_id if latest_request is not None else None,
            latest_status_text=latest_status_text,
            latest_issue_text=latest_issue_text,
            blocker=blocker,
            next_action=next_action,
            updated_at=self._now(),
            age_hours=derived_age_hours,
            age_bucket=self._age_bucket_for_stage(stage, derived_age_hours),
        )

    @staticmethod
    def _matching_requests(records: list[PartRequestRecord], reference: str) -> list[PartRequestRecord]:
        normalized_reference = reference.strip().casefold()
        return [record for record in records if record.reference.strip().casefold() == normalized_reference]

    @staticmethod
    def _parse_sr_id(raw: object) -> int | None:
        text = str(raw or "").strip()
        return int(text) if text.isdigit() else None

    @staticmethod
    def _reference_sr_id(reference: str) -> int | None:
        candidate = reference.strip().upper()
        if not candidate.startswith("SR-"):
            return None
        value = candidate[3:]
        return int(value) if value.isdigit() else None

    @staticmethod
    def _event_id(*, source: str, event_type: str, sr_id: int | None, timestamp: str) -> str:
        target = f"SR-{sr_id}" if sr_id is not None else "global"
        return f"{source}:{event_type}:{target}:{timestamp}"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def _user_label(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if self.technician_directory_service is not None:
            return self.technician_directory_service.discord_mention(user_id)
        return f"<@{user_id}>"

    def _was_notified_recently(self, *, item_id: str, hours: int) -> bool:
        cutoff_hours = max(hours, 0)
        now = datetime.now(UTC)
        for event in reversed(self.store.load().events):
            if event.source != "ops_hub.policy" or event.event_type != "attention_notice":
                continue
            if event.metadata.get("item_id") != item_id:
                continue
            occurred_at = self._parse_datetime(event.occurred_at)
            if occurred_at is None:
                continue
            age_hours = (now - occurred_at).total_seconds() / 3600
            if age_hours <= cutoff_hours:
                return True
        return False

    def _age_hours(self, raw_timestamp: str | None) -> int | None:
        parsed = self._parse_datetime(raw_timestamp)
        if parsed is None:
            return None
        delta = datetime.now(UTC) - parsed
        return max(int(delta.total_seconds() // 3600), 0)

    def _age_bucket_for_stage(self, stage: str | None, age_hours: int | None) -> str | None:
        if age_hours is None:
            return None
        warm_hours, stale_hours, urgent_hours = self._sla_thresholds_for_stage(stage)
        if age_hours < warm_hours:
            return "fresh"
        if age_hours < stale_hours:
            return "warm"
        if age_hours < urgent_hours:
            return "stale"
        return "urgent"

    def _sla_thresholds_for_stage(self, stage: str | None) -> tuple[int, int, int]:
        if stage is None:
            return 4, 24, 72
        return self.attention_sla_hours.get(stage, (4, 24, 72))

    @staticmethod
    def _parse_datetime(raw_timestamp: str | None) -> datetime | None:
        if raw_timestamp is None or not str(raw_timestamp).strip():
            return None
        candidate = str(raw_timestamp).strip()
        for parser in (
            lambda value: datetime.fromisoformat(value),
            lambda value: datetime.strptime(value, "%Y-%m-%d %H:%M"),
            lambda value: datetime.strptime(value, "%Y-%m-%dT%H:%M:%S"),
        ):
            try:
                parsed = parser(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
            except ValueError:
                continue
        return None
