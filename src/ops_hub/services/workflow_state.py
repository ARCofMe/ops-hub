"""Ops Hub workflow-state derivation and event capture."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
import threading
import time
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

logger = logging.getLogger(__name__)


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
            "new_sr_triage": (2, 8, 24),
            "model_serial_needed": (2, 8, 24),
            "likely_parts_previsit": (4, 12, 24),
            "diagnostic_required": (4, 12, 24),
            "previsit_quote_needed": (2, 8, 24),
            "issue_reported": (2, 12, 24),
            "part_received": (8, 24, 72),
            "part_ready": (4, 24, 48),
            "quote_needed": (2, 8, 24),
            "requested": (8, 24, 48),
            "ordered": (12, 48, 96),
            "received": (8, 24, 72),
            "no_recent_parts_context": (24, 72, 120),
        }
    )
    refresh_cache_ttl_seconds: float = 10.0
    _refresh_mutex: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _last_unfiltered_refresh_at: float = field(default=0.0, init=False, repr=False)
    _last_unfiltered_refresh_mapping_ids: tuple[int, ...] = field(default_factory=tuple, init=False, repr=False)
    _last_unfiltered_scanned_jobs: int = field(default=0, init=False, repr=False)

    def current_snapshot(self) -> WorkflowStateSnapshot:
        """Return the current workflow snapshot."""
        return self.store.load()

    def attention_metrics(self, snapshot: WorkflowStateSnapshot | None = None) -> dict[str, object]:
        """Summarize current attention state for reporting surfaces."""
        current_snapshot = snapshot or self.store.load()
        items = current_snapshot.attention_items
        status_counts = self._count_by(items, key=lambda item: item.status)
        stage_counts = self._count_by(items, key=lambda item: item.stage_label)
        age_counts = self._count_by(items, key=lambda item: item.age_bucket or "unknown")
        assigned_owner_items = sum(1 for item in items if item.assigned_owner_discord_user_id is not None)
        urgent_open_items = sum(1 for item in items if item.age_bucket == "urgent" and item.status == "open")
        urgent_suppressed_items = sum(1 for item in items if item.age_bucket == "urgent" and item.status != "open")
        return {
            "total_items": len(items),
            "status_counts": status_counts,
            "stage_counts": stage_counts,
            "age_counts": age_counts,
            "assigned_owner_items": assigned_owner_items,
            "unassigned_owner_items": max(len(items) - assigned_owner_items, 0),
            "urgent_open_items": urgent_open_items,
            "urgent_suppressed_items": urgent_suppressed_items,
        }

    async def run_policy_cycle(self, *, emit_notices: bool = True) -> dict[str, int]:
        """Refresh workflow state and optionally emit deduplicated urgent notices."""
        mappings = self.technician_directory_service.mapping_records() if self.technician_directory_service is not None else []
        _, attention_items = await self.refresh_dispatch_attention(mappings)
        urgent_items = [item for item in attention_items if item.age_bucket == "urgent" and item.status == "open"]
        reopened_urgent_items = [item for item in urgent_items if self._was_reopened_recently(item=item, hours=24)]
        owner_gap_urgent_items = [item for item in urgent_items if item.assigned_owner_discord_user_id is None]
        suppressed_urgent_items = [
            item
            for item in attention_items
            if item.age_bucket == "urgent"
            and item.status != "open"
            and self._suppression_age_hours(item=item) >= 24
        ]
        notices_sent = 0
        suppressed_reminders_sent = 0
        routed_topics: set[str] = set()
        for item in urgent_items:
            qualifiers: list[str] = []
            if item in reopened_urgent_items:
                qualifiers.append("reopened")
            if item in owner_gap_urgent_items:
                qualifiers.append("owner_gap")
            topic = self._policy_topic_for_item(item, qualifiers=tuple(qualifiers))
            if emit_notices and self._was_notified_recently(item_id=item.item_id, hours=6):
                continue
            if emit_notices and self.notification_service is not None:
                await self.notification_service.send_notice(
                    topic=topic,
                    message=(
                        f"{item.reference} needs dispatch attention. "
                        f"Stage: {item.stage_label}. "
                        f"Age: {item.age_hours or 0}h ({item.age_bucket}). "
                        f"{item.next_action or ''}".strip()
                    ),
                )
                routed_topics.add(topic)
            if emit_notices:
                notice_kind = ".".join(qualifiers) if qualifiers else "urgent"
                is_reopened_notice = "reopened" in qualifiers
                self.record_event(
                    event_type="attention_reopened_notice" if is_reopened_notice else "attention_notice",
                    source="ops_hub.policy",
                    sr_id=item.sr_id,
                    reference=item.reference,
                    summary=(
                        f"Sent reopened urgent attention notice for {item.reference}."
                        if is_reopened_notice
                        else f"Sent urgent attention notice for {item.reference}."
                    ),
                    details=item.next_action,
                    metadata={
                        "item_id": item.item_id,
                        "age_bucket": item.age_bucket or "",
                        "topic": topic,
                        "notice_kind": notice_kind,
                    },
                )
                notices_sent += 1
        for item in suppressed_urgent_items:
            topic = self._policy_topic_for_item(item, qualifiers=("suppressed",))
            if emit_notices and self._was_policy_event_recently(
                item_id=item.item_id,
                event_types={"attention_suppressed_reminder"},
                hours=24,
            ):
                continue
            if emit_notices and self.notification_service is not None:
                await self.notification_service.send_notice(
                    topic=topic,
                    message=(
                        f"{item.reference} remains urgent but is currently `{item.status}`. "
                        f"Stage: {item.stage_label}. "
                        f"Age: {item.age_hours or 0}h ({item.age_bucket}). "
                        f"Review whether it should stay suppressed."
                    ),
                )
                routed_topics.add(topic)
            if emit_notices:
                self.record_event(
                    event_type="attention_suppressed_reminder",
                    source="ops_hub.policy",
                    sr_id=item.sr_id,
                    reference=item.reference,
                    summary=f"Sent suppressed urgent reminder for {item.reference}.",
                    details=item.next_action,
                    metadata={
                        "item_id": item.item_id,
                        "age_bucket": item.age_bucket or "",
                        "topic": topic,
                        "notice_kind": "suppressed",
                    },
                )
                suppressed_reminders_sent += 1
        return {
            "attention_items": len(attention_items),
            "urgent_items": len(urgent_items),
            "reopened_urgent_items": len(reopened_urgent_items),
            "owner_gap_urgent_items": len(owner_gap_urgent_items),
            "suppressed_urgent_items": len(suppressed_urgent_items),
            "notices_sent": notices_sent,
            "suppressed_reminders_sent": suppressed_reminders_sent,
            "topics_count": len(routed_topics),
        }

    def acknowledge_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> AttentionItemRecord:
        """Acknowledge one attention item and suppress policy noise until it changes."""
        def mutate(item: AttentionItemRecord) -> None:
            self._apply_acknowledge(item)
            item.acknowledged_by_user_id = actor_user_id

        item = self._update_attention_item(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=actor_user_id,
            mutate=mutate,
        )
        self.record_event(
            event_type="attention_acknowledged",
            source="ops_hub.dispatch",
            sr_id=sr_id,
            reference=item.reference,
            actor_user_id=actor_user_id,
            actor_label=self._user_label(actor_user_id),
            summary=f"Acknowledged dispatch attention for {item.reference}.",
            details=item.stage_label,
            metadata={"item_id": item.item_id, "stage": item.stage},
        )
        return item

    def snooze_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        hours: int,
        actor_user_id: int,
    ) -> AttentionItemRecord:
        """Snooze one attention item for a bounded number of hours."""
        snooze_hours = max(hours, 1)

        def mutate(item: AttentionItemRecord) -> None:
            item.status = "snoozed"
            item.snoozed_until = self._shift_now(hours=snooze_hours)
            item.snoozed_by_user_id = actor_user_id
            item.acknowledged_at = None
            item.acknowledged_by_user_id = None

        item = self._update_attention_item(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=actor_user_id,
            mutate=mutate,
        )
        self.record_event(
            event_type="attention_snoozed",
            source="ops_hub.dispatch",
            sr_id=sr_id,
            reference=item.reference,
            actor_user_id=actor_user_id,
            actor_label=self._user_label(actor_user_id),
            summary=f"Snoozed dispatch attention for {item.reference}.",
            details=f"{item.stage_label} until {item.snoozed_until}",
            metadata={"item_id": item.item_id, "stage": item.stage, "hours": str(snooze_hours)},
        )
        return item

    def assign_attention_owner(
        self,
        *,
        sr_id: int,
        stage: str | None,
        assigned_owner_discord_user_id: int,
        actor_user_id: int,
    ) -> AttentionItemRecord:
        """Assign one attention item to a specific follow-up owner."""

        def mutate(item: AttentionItemRecord) -> None:
            item.assigned_owner_discord_user_id = assigned_owner_discord_user_id

        item = self._update_attention_item(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=actor_user_id,
            mutate=mutate,
        )
        self.record_event(
            event_type="attention_owner_assigned",
            source="ops_hub.dispatch",
            sr_id=sr_id,
            reference=item.reference,
            actor_user_id=actor_user_id,
            actor_label=self._user_label(actor_user_id),
            summary=f"Assigned dispatch attention owner for {item.reference}.",
            details=f"{item.stage_label} -> {self._user_label(assigned_owner_discord_user_id)}",
            metadata={
                "item_id": item.item_id,
                "stage": item.stage,
                "assigned_owner_discord_user_id": str(assigned_owner_discord_user_id),
            },
        )
        return item

    def clear_attention_owner(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> AttentionItemRecord:
        """Clear any explicit follow-up owner on one attention item."""

        def mutate(item: AttentionItemRecord) -> None:
            item.assigned_owner_discord_user_id = None

        item = self._update_attention_item(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=actor_user_id,
            mutate=mutate,
        )
        self.record_event(
            event_type="attention_owner_cleared",
            source="ops_hub.dispatch",
            sr_id=sr_id,
            reference=item.reference,
            actor_user_id=actor_user_id,
            actor_label=self._user_label(actor_user_id),
            summary=f"Cleared dispatch attention owner for {item.reference}.",
            details=item.stage_label,
            metadata={"item_id": item.item_id, "stage": item.stage},
        )
        return item

    def reopen_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> AttentionItemRecord:
        """Reopen one attention item and return it to active policy tracking."""

        def mutate(item: AttentionItemRecord) -> None:
            item.status = "open"
            item.acknowledged_at = None
            item.acknowledged_by_user_id = None
            item.snoozed_until = None
            item.snoozed_by_user_id = None

        item = self._update_attention_item(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=actor_user_id,
            mutate=mutate,
        )
        self.record_event(
            event_type="attention_reopened",
            source="ops_hub.dispatch",
            sr_id=sr_id,
            reference=item.reference,
            actor_user_id=actor_user_id,
            actor_label=self._user_label(actor_user_id),
            summary=f"Reopened dispatch attention for {item.reference}.",
            details=item.stage_label,
            metadata={"item_id": item.item_id, "stage": item.stage},
        )
        return item

    def unsnooze_attention(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
    ) -> AttentionItemRecord:
        """Remove a snooze and return the attention item to open state."""

        def mutate(item: AttentionItemRecord) -> None:
            item.status = "open"
            item.snoozed_until = None
            item.snoozed_by_user_id = None

        item = self._update_attention_item(
            sr_id=sr_id,
            stage=stage,
            actor_user_id=actor_user_id,
            mutate=mutate,
        )
        self.record_event(
            event_type="attention_unsnoozed",
            source="ops_hub.dispatch",
            sr_id=sr_id,
            reference=item.reference,
            actor_user_id=actor_user_id,
            actor_label=self._user_label(actor_user_id),
            summary=f"Unsnoozed dispatch attention for {item.reference}.",
            details=item.stage_label,
            metadata={"item_id": item.item_id, "stage": item.stage},
        )
        return item

    def set_triage_disposition(
        self,
        *,
        sr_id: int,
        disposition: str,
        actor_user_id: int,
        details: str | None = None,
    ) -> AttentionItemRecord | None:
        """Persist one triage disposition decision and update any current triage item."""
        normalized_disposition = self._normalize_triage_disposition(disposition)
        if normalized_disposition is None:
            raise ValueError(
                "Triage disposition must be one of: `schedule_normal`, `collect_info`, `parts_first`, `diag_first`, `quote_before_schedule`."
            )
        reference = f"SR-{sr_id}"
        triage_stage = self._triage_stage_for_disposition(normalized_disposition)
        triage_label = self._triage_stage_label(triage_stage) if triage_stage is not None else "Schedule Normal"
        summary = (
            f"Set triage disposition for {reference} to {triage_label}."
            if triage_stage is not None
            else f"Cleared triage queue for {reference} and marked it schedule-normal."
        )
        self.record_event(
            event_type="triage_disposition_set",
            source="ops_hub.dispatch",
            sr_id=sr_id,
            reference=reference,
            actor_user_id=actor_user_id,
            actor_label=self._user_label(actor_user_id),
            summary=summary,
            details=details,
            metadata={
                "disposition": normalized_disposition,
                **({"triage_stage": triage_stage} if triage_stage is not None else {}),
            },
        )

        snapshot = self.store.load()
        existing_triage_item = self._find_existing_triage_item(snapshot.attention_items, reference=reference)
        if existing_triage_item is None:
            return None
        if triage_stage is None:
            snapshot.attention_items = [item for item in snapshot.attention_items if item.item_id != existing_triage_item.item_id]
            snapshot.updated_at = self._now()
            self.store.save(snapshot)
            return None

        existing_triage_item.item_id = f"dispatch:{reference}:{triage_stage}"
        existing_triage_item.stage = triage_stage
        existing_triage_item.stage_label = self._triage_stage_label(triage_stage)
        existing_triage_item.details = self._triage_details(stage=triage_stage, service_request_status=None, user_details=details)
        existing_triage_item.next_action = self._triage_next_action(stage=triage_stage)
        existing_triage_item.last_seen_at = self._now()
        existing_triage_item.age_hours = self._age_hours(existing_triage_item.first_seen_at)
        existing_triage_item.age_bucket = self._age_bucket_for_stage(triage_stage, existing_triage_item.age_hours)
        snapshot.updated_at = self._now()
        self.store.save(snapshot)
        return existing_triage_item

    def describe_attention_history(self, *, sr_id: int, stage: str | None = None) -> CommandResult:
        """Render recent workflow-state history for one attention item."""
        snapshot = self.store.load()
        item = self._find_attention_item(snapshot.attention_items, sr_id=sr_id, stage=stage)
        history = self._attention_history_events(snapshot.events, item=item)

        lines = [
            f"**Attention History {item.reference}**",
            f"Stage: `{item.stage_label}`",
            f"Status: `{item.status}`",
        ]
        if item.assigned_owner_discord_user_id is not None:
            lines.append(f"Follow-up owner: {self._user_label(item.assigned_owner_discord_user_id)}")
        if item.snoozed_until:
            lines.append(f"Snoozed until: `{item.snoozed_until}`")
        if not history:
            lines.extend(["", "No workflow actions have been recorded for this attention item yet."])
            return CommandResult(message="\n".join(lines))

        for index, event in enumerate(history[:10], start=1):
            lines.extend(
                [
                    "",
                    f"{index}. `{event.occurred_at}` `{event.event_type}`",
                    event.summary,
                ]
            )
            if event.actor_label:
                lines.append(f"Actor: {event.actor_label}")
            if event.details:
                lines.append(f"Detail: {event.details}")
        if len(history) > 10:
            lines.extend(["", f"...and {len(history) - 10} more workflow event(s)"])
        return CommandResult(message="\n".join(lines))

    def get_attention_item(self, *, item_id: str) -> AttentionItemRecord:
        """Return one persisted attention item by stable item id."""
        snapshot = self.store.load()
        for item in snapshot.attention_items:
            if item.item_id == item_id:
                return item
        raise ValueError(f"No attention item is currently available for `{item_id}`.")

    def attention_history(self, *, item_id: str) -> list[WorkflowEventRecord]:
        """Return persisted workflow history for one attention item."""
        snapshot = self.store.load()
        item = self.get_attention_item(item_id=item_id)
        return self._attention_history_events(snapshot.events, item=item)

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
        started_at = time.perf_counter()
        allowed_stages = {
            "new_sr_triage": "New SR Triage",
            "model_serial_needed": "Model/Serial Needed",
            "likely_parts_previsit": "Likely Parts Previsit",
            "diagnostic_required": "Diagnostic Required",
            "previsit_quote_needed": "Previsit Quote Needed",
            "issue_reported": "Issue Reported",
            "part_received": "Received",
            "part_ready": "Ready for Scheduling",
            "quote_needed": "Quote Needed",
        }
        normalized_stage_filter = None if stage_filter is None else stage_filter.strip().lower().replace(" ", "_")

        if technician_bluefolder_user_id is not None:
            mappings = [record for record in mappings if record.bluefolder_user_id == technician_bluefolder_user_id]

        if self._can_use_unfiltered_refresh_cache(
            mappings=mappings,
            normalized_stage_filter=normalized_stage_filter,
            age_bucket=age_bucket,
            owner_discord_user_id=owner_discord_user_id,
            technician_bluefolder_user_id=technician_bluefolder_user_id,
        ):
            snapshot = self.store.load()
            items = list(snapshot.attention_items)
            logger.info(
                "Workflow attention reused cached refresh",
                extra={
                    "mapped_techs": len(mappings),
                    "scanned_jobs": self._last_unfiltered_scanned_jobs,
                    "attention_items": len(items),
                    "parts_cases": len(snapshot.parts_cases),
                    "duration_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )
            return self._last_unfiltered_scanned_jobs, items

        with self._refresh_mutex:
            if self._can_use_unfiltered_refresh_cache(
                mappings=mappings,
                normalized_stage_filter=normalized_stage_filter,
                age_bucket=age_bucket,
                owner_discord_user_id=owner_discord_user_id,
                technician_bluefolder_user_id=technician_bluefolder_user_id,
            ):
                snapshot = self.store.load()
                items = list(snapshot.attention_items)
                logger.info(
                    "Workflow attention reused cached refresh",
                    extra={
                        "mapped_techs": len(mappings),
                        "scanned_jobs": self._last_unfiltered_scanned_jobs,
                        "attention_items": len(items),
                        "parts_cases": len(snapshot.parts_cases),
                        "duration_ms": int((time.perf_counter() - started_at) * 1000),
                    },
                )
                return self._last_unfiltered_scanned_jobs, items

            scanned_jobs = 0
            attention_items: list[AttentionItemRecord] = []
            parts_cases: dict[str, PartsCaseRecord] = {}
            current_snapshot = self.store.load()
            previous_items = {item.item_id: item for item in current_snapshot.attention_items}
            parts_records = self.parts_cannon_service.request_store.load()

            per_record_started_at = time.perf_counter()
            per_record_results = await asyncio.gather(
                *(
                    self._refresh_attention_for_record(
                        record=record,
                        allowed_stages=allowed_stages,
                        normalized_stage_filter=normalized_stage_filter,
                        age_bucket=age_bucket,
                        owner_discord_user_id=owner_discord_user_id,
                        previous_items=previous_items,
                        parts_records=parts_records,
                    )
                    for record in mappings
                )
            )
            per_record_duration_ms = int((time.perf_counter() - per_record_started_at) * 1000)
            for record_scanned_jobs, record_attention_items, record_parts_cases in per_record_results:
                scanned_jobs += record_scanned_jobs
                attention_items.extend(record_attention_items)
                for parts_case in record_parts_cases:
                    parts_cases[parts_case.case_id] = parts_case

            extra_parts_started_at = time.perf_counter()
            extra_parts_cases = await asyncio.gather(
                *(self._parts_case_from_reference(reference=reference, parts_records=parts_records) for reference in {record.reference for record in parts_records})
            )
            extra_parts_duration_ms = int((time.perf_counter() - extra_parts_started_at) * 1000)
            for parts_case in extra_parts_cases:
                parts_cases[parts_case.case_id] = parts_case

            updated_snapshot = WorkflowStateSnapshot(
                updated_at=self._now(),
                attention_items=attention_items,
                parts_cases=sorted(parts_cases.values(), key=lambda item: (item.reference, item.stage)),
                events=current_snapshot.events,
            )
            self.store.save(updated_snapshot)
            if (
                normalized_stage_filter is None
                and age_bucket is None
                and owner_discord_user_id is None
                and technician_bluefolder_user_id is None
            ):
                self._last_unfiltered_refresh_at = time.monotonic()
                self._last_unfiltered_refresh_mapping_ids = tuple(sorted(record.bluefolder_user_id for record in mappings))
                self._last_unfiltered_scanned_jobs = scanned_jobs
            logger.info(
                "Workflow attention refreshed",
                extra={
                    "mapped_techs": len(mappings),
                    "scanned_jobs": scanned_jobs,
                    "attention_items": len(attention_items),
                    "parts_cases": len(updated_snapshot.parts_cases),
                    "duration_ms": int((time.perf_counter() - started_at) * 1000),
                    "per_record_ms": per_record_duration_ms,
                    "extra_parts_ms": extra_parts_duration_ms,
                },
            )
            return scanned_jobs, attention_items

    def _can_use_unfiltered_refresh_cache(
        self,
        *,
        mappings: list[TechnicianMappingRecord],
        normalized_stage_filter: str | None,
        age_bucket: str | None,
        owner_discord_user_id: int | None,
        technician_bluefolder_user_id: int | None,
    ) -> bool:
        """Return whether a recent unfiltered refresh can be safely reused."""
        if normalized_stage_filter is not None or age_bucket is not None or owner_discord_user_id is not None:
            return False
        if technician_bluefolder_user_id is not None:
            return False
        if (time.monotonic() - self._last_unfiltered_refresh_at) > self.refresh_cache_ttl_seconds:
            return False
        mapping_ids = tuple(sorted(record.bluefolder_user_id for record in mappings))
        return mapping_ids == self._last_unfiltered_refresh_mapping_ids

    async def _refresh_attention_for_record(
        self,
        *,
        record: TechnicianMappingRecord,
        allowed_stages: dict[str, str],
        normalized_stage_filter: str | None,
        age_bucket: str | None,
        owner_discord_user_id: int | None,
        previous_items: dict[str, AttentionItemRecord],
        parts_records: list[PartRequestRecord],
    ) -> tuple[int, list[AttentionItemRecord], list[PartsCaseRecord]]:
        """Derive current attention and parts-case state for one mapped technician."""
        assignments = await self.bluefolder_service.get_assignments_for_user_today(
            record.bluefolder_user_id,
            include_subjects=False,
        )
        assignment_results = await asyncio.gather(
            *(
                self._refresh_attention_for_assignment(
                    record=record,
                    assignment=assignment,
                    allowed_stages=allowed_stages,
                    normalized_stage_filter=normalized_stage_filter,
                    age_bucket=age_bucket,
                    owner_discord_user_id=owner_discord_user_id,
                    previous_items=previous_items,
                    parts_records=parts_records,
                )
                for assignment in assignments[:10]
            )
        )

        scanned_jobs = 0
        attention_items: list[AttentionItemRecord] = []
        parts_cases: list[PartsCaseRecord] = []
        for result in assignment_results:
            if result is None:
                continue
            scanned_jobs += 1
            record_attention_items, parts_case = result
            attention_items.extend(record_attention_items)
            parts_cases.append(parts_case)
        return scanned_jobs, attention_items, parts_cases

    async def _refresh_attention_for_assignment(
        self,
        *,
        record: TechnicianMappingRecord,
        assignment: dict[str, object],
        allowed_stages: dict[str, str],
        normalized_stage_filter: str | None,
        age_bucket: str | None,
        owner_discord_user_id: int | None,
        previous_items: dict[str, AttentionItemRecord],
        parts_records: list[PartRequestRecord],
    ) -> tuple[list[AttentionItemRecord], PartsCaseRecord] | None:
        """Derive attention and parts-case state for one assigned SR."""
        sr_id = self._parse_sr_id(assignment.get("serviceRequestId"))
        if sr_id is None:
            return None
        reference = f"SR-{sr_id}"
        snapshot, job_summary = await asyncio.gather(
            self.bluefolder_service.get_parts_snapshot(sr_id),
            self.bluefolder_service.get_job_summary(reference, include_customer_contacts=False),
        )
        matching_requests = self._matching_requests(parts_records, reference)
        parts_case = self._build_parts_case(
            reference=reference,
            sr_id=sr_id,
            snapshot=snapshot,
            matching_requests=matching_requests,
        )

        location = " ".join(part for part in [assignment.get("city"), assignment.get("state")] if part).strip()
        route_label = str(assignment.get("routeLabel") or assignment.get("window") or assignment.get("timeWindow") or "").strip() or None
        summary = str(assignment.get("subject") or "Unlabeled Service Request")
        derived_items = self._build_assignment_attention_items(
            record=record,
            reference=reference,
            sr_id=sr_id,
            assignment_summary=summary,
            location=location or None,
            route_label=route_label,
            parts_snapshot=snapshot,
            job_summary=job_summary,
            previous_items=previous_items,
        )
        filtered_items = [
            derived_item
            for derived_item in derived_items
            if derived_item.stage in allowed_stages
            and (normalized_stage_filter is None or derived_item.stage == normalized_stage_filter)
            and (age_bucket is None or derived_item.age_bucket == age_bucket)
            and (owner_discord_user_id is None or derived_item.owner_discord_user_id == owner_discord_user_id)
        ]
        return filtered_items, parts_case

    async def _parts_case_from_reference(
        self,
        *,
        reference: str,
        parts_records: list[PartRequestRecord],
    ) -> PartsCaseRecord:
        """Build a parts case from tracked-request state even when no active assignment is visible."""
        sr_id = self._reference_sr_id(reference)
        matching_requests = self._matching_requests(parts_records, reference)
        snapshot = await self.bluefolder_service.get_parts_snapshot(sr_id) if sr_id is not None else None
        return self._build_parts_case(
            reference=reference,
            sr_id=sr_id,
            snapshot=snapshot,
            matching_requests=matching_requests,
        )

    def _build_assignment_attention_items(
        self,
        *,
        record: TechnicianMappingRecord,
        reference: str,
        sr_id: int,
        assignment_summary: str,
        location: str | None,
        route_label: str | None,
        parts_snapshot: PartsLifecycleSnapshot | None,
        job_summary,
        previous_items: dict[str, AttentionItemRecord],
    ) -> list[AttentionItemRecord]:
        """Build any current attention items for one assigned SR."""
        items: list[AttentionItemRecord] = []
        status_text = getattr(job_summary, "service_request_status", None)
        triage_disposition = self._triage_disposition_for_reference(reference=reference)
        triage_stage = self._triage_stage_from_status(status_text)
        if triage_disposition is not None:
            triage_stage = self._triage_stage_for_disposition(triage_disposition)
        if triage_stage is not None:
            item_id = f"dispatch:{reference}:{triage_stage}"
            previous = previous_items.get(item_id) or self._find_existing_triage_item(previous_items.values(), reference=reference)
            first_seen_at = (
                previous.first_seen_at
                if previous is not None and previous.first_seen_at
                else self._triage_first_seen_at(reference=reference)
                or self._now()
            )
            triage_item = AttentionItemRecord(
                item_id=item_id,
                sr_id=sr_id,
                reference=reference,
                category="triage",
                status="open",
                stage=triage_stage,
                stage_label=self._triage_stage_label(triage_stage),
                summary=assignment_summary,
                details=self._triage_details(stage=triage_stage, service_request_status=status_text),
                location=location,
                route_label=route_label,
                owner_discord_user_id=record.discord_user_id,
                owner_bluefolder_user_id=record.bluefolder_user_id,
                next_action=self._triage_next_action(stage=triage_stage),
                first_seen_at=first_seen_at,
                last_seen_at=self._now(),
                age_hours=self._age_hours(first_seen_at),
                age_bucket=self._age_bucket_for_stage(triage_stage, self._age_hours(first_seen_at)),
            )
            self._carry_attention_state(triage_item, previous)
            items.append(triage_item)

        if parts_snapshot is not None:
            item_id = f"dispatch:{reference}:{parts_snapshot.stage}"
            previous = previous_items.get(item_id)
            first_seen_at = (
                previous.first_seen_at
                if previous is not None and previous.first_seen_at
                else parts_snapshot.latest_issue_at
                or parts_snapshot.latest_status_at
                or self._now()
            )
            derived_item = AttentionItemRecord(
                item_id=item_id,
                sr_id=sr_id,
                reference=reference,
                category="dispatch",
                status="open",
                stage=parts_snapshot.stage,
                stage_label=parts_snapshot.stage_label,
                summary=assignment_summary,
                details=parts_snapshot.latest_status_text or parts_snapshot.latest_issue_text,
                location=location,
                route_label=route_label,
                owner_discord_user_id=record.discord_user_id,
                owner_bluefolder_user_id=record.bluefolder_user_id,
                next_action=self.bluefolder_service.recommend_next_action(parts_snapshot),
                first_seen_at=first_seen_at,
                last_seen_at=self._now(),
                age_hours=self._age_hours(first_seen_at),
                age_bucket=self._age_bucket_for_stage(parts_snapshot.stage, self._age_hours(first_seen_at)),
            )
            self._carry_attention_state(derived_item, previous)
            items.append(derived_item)

        if self._is_quote_needed_status(status_text):
            quote_subtype = self._quote_needed_subtype(status_text)
            item_id = f"dispatch:{reference}:quote_needed:{quote_subtype}"
            previous = previous_items.get(item_id)
            first_seen_at = previous.first_seen_at if previous is not None and previous.first_seen_at else self._now()
            derived_item = AttentionItemRecord(
                item_id=item_id,
                sr_id=sr_id,
                reference=reference,
                category="dispatch",
                status="open",
                stage="quote_needed",
                stage_label="Quote Needed",
                summary=assignment_summary,
                details=self._quote_needed_details(status_text),
                location=location,
                route_label=route_label,
                owner_discord_user_id=record.discord_user_id,
                owner_bluefolder_user_id=record.bluefolder_user_id,
                next_action=self._quote_needed_next_action(status_text),
                first_seen_at=first_seen_at,
                last_seen_at=self._now(),
                age_hours=self._age_hours(first_seen_at),
                age_bucket=self._age_bucket_for_stage("quote_needed", self._age_hours(first_seen_at)),
            )
            self._carry_attention_state(derived_item, previous)
            items.append(derived_item)
        return items

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
            return self.technician_directory_service.display_label(user_id)
        return str(user_id)

    def _carry_attention_state(
        self,
        item: AttentionItemRecord,
        previous: AttentionItemRecord | None,
    ) -> None:
        """Preserve manual workflow actions when the derived item is recomputed."""
        if previous is None:
            return
        item.assigned_owner_discord_user_id = previous.assigned_owner_discord_user_id
        item.acknowledged_at = previous.acknowledged_at
        item.acknowledged_by_user_id = previous.acknowledged_by_user_id
        item.snoozed_until = previous.snoozed_until
        item.snoozed_by_user_id = previous.snoozed_by_user_id
        if self._is_snooze_active(previous):
            item.status = "snoozed"
            return
        item.snoozed_until = None
        item.snoozed_by_user_id = None
        if previous.acknowledged_at:
            item.status = "acknowledged"

    @staticmethod
    def _attention_history_events(
        events: list[WorkflowEventRecord],
        *,
        item: AttentionItemRecord,
    ) -> list[WorkflowEventRecord]:
        relevant = [
            event
            for event in events
            if event.metadata.get("item_id") == item.item_id
            or (
                event.reference == item.reference
                and event.metadata.get("stage") == item.stage
                and event.source.startswith("ops_hub.dispatch")
            )
        ]
        return sorted(relevant, key=lambda event: event.occurred_at or "", reverse=True)

    @staticmethod
    def _count_by(
        items: list[AttentionItemRecord],
        *,
        key,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            label = str(key(item) or "unknown")
            counts[label] = counts.get(label, 0) + 1
        return counts

    def _update_attention_item(
        self,
        *,
        sr_id: int,
        stage: str | None,
        actor_user_id: int,
        mutate,
    ) -> AttentionItemRecord:
        """Update one persisted attention item in place."""
        snapshot = self.store.load()
        item = self._find_attention_item(snapshot.attention_items, sr_id=sr_id, stage=stage)
        mutate(item)
        item.last_seen_at = self._now()
        snapshot.updated_at = self._now()
        self.store.save(snapshot)
        return item

    def _apply_acknowledge(self, item: AttentionItemRecord) -> None:
        item.status = "acknowledged"
        item.acknowledged_at = self._now()
        item.snoozed_until = None
        item.snoozed_by_user_id = None

    def _find_attention_item(
        self,
        items: list[AttentionItemRecord],
        *,
        sr_id: int,
        stage: str | None,
    ) -> AttentionItemRecord:
        reference = f"SR-{sr_id}"
        normalized_stage = None if stage is None else stage.strip().lower().replace(" ", "_")
        matches = [item for item in items if item.sr_id == sr_id or item.reference == reference]
        if normalized_stage is not None:
            matches = [item for item in matches if item.stage == normalized_stage]
        if not matches:
            target = f"{reference} ({normalized_stage})" if normalized_stage is not None else reference
            raise ValueError(f"No attention item is currently available for {target}.")
        if len(matches) > 1:
            raise ValueError(f"Multiple attention items match {reference}; provide a stage.")
        return matches[0]

    def _is_snooze_active(self, item: AttentionItemRecord) -> bool:
        snoozed_until = self._parse_datetime(item.snoozed_until)
        if snoozed_until is None:
            return False
        return snoozed_until > datetime.now(UTC)

    @staticmethod
    def _shift_now(*, hours: int) -> str:
        return (datetime.now(UTC) + timedelta(hours=hours)).isoformat(timespec="seconds")

    def _was_notified_recently(self, *, item_id: str, hours: int) -> bool:
        return self._was_policy_event_recently(
            item_id=item_id,
            event_types={"attention_notice", "attention_reopened_notice"},
            hours=hours,
            allowed_sources={"ops_hub.policy"},
        )

    def _was_policy_event_recently(
        self,
        *,
        item_id: str,
        event_types: set[str],
        hours: int,
        allowed_sources: set[str] | None = None,
    ) -> bool:
        cutoff_hours = max(hours, 0)
        now = datetime.now(UTC)
        for event in reversed(self.store.load().events):
            if allowed_sources is not None and event.source not in allowed_sources:
                continue
            if event.event_type not in event_types:
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

    @staticmethod
    def _policy_topic_for_item(item: AttentionItemRecord, *, qualifiers: tuple[str, ...] = ()) -> str:
        if item.stage in {
            "new_sr_triage",
            "model_serial_needed",
            "likely_parts_previsit",
            "diagnostic_required",
            "previsit_quote_needed",
        }:
            base = f"dispatch.triage_attention.{item.stage}"
        elif item.stage == "part_ready":
            base = "dispatch.scheduling_attention"
        elif item.stage == "issue_reported":
            base = "dispatch.parts_issue_attention"
        elif item.stage == "part_received":
            base = "parts.received_attention"
        elif item.stage == "quote_needed":
            base = "dispatch.quote_needed_attention"
        else:
            base = f"dispatch.attention.{item.stage}"
        topic = base
        if item.stage == "quote_needed":
            quote_subtype = WorkflowStateService._quote_needed_subtype_from_item(item)
            if quote_subtype != "customer":
                topic = f"{topic}.{quote_subtype}"
        for qualifier in qualifiers:
            normalized = qualifier.strip().lower().replace(" ", "_")
            if normalized:
                topic = f"{topic}.{normalized}"
        return topic

    def _was_reopened_recently(self, *, item: AttentionItemRecord, hours: int) -> bool:
        return self._was_policy_event_recently(
            item_id=item.item_id,
            event_types={"attention_reopened"},
            hours=hours,
            allowed_sources={"ops_hub.dispatch"},
        )

    def _suppression_age_hours(self, *, item: AttentionItemRecord) -> int:
        relevant_event_types = {"attention_acknowledged", "attention_snoozed"}
        latest = self._latest_event_time(item_id=item.item_id, event_types=relevant_event_types)
        if latest is None:
            latest = self._parse_datetime(item.acknowledged_at or item.snoozed_until)
        if latest is None:
            return 0
        return max(int((datetime.now(UTC) - latest).total_seconds() // 3600), 0)

    def _latest_event_time(self, *, item_id: str, event_types: set[str]) -> datetime | None:
        latest: datetime | None = None
        for event in self.store.load().events:
            if event.source not in {"ops_hub.dispatch", "ops_hub.policy"}:
                continue
            if event.event_type not in event_types:
                continue
            if event.metadata.get("item_id") != item_id:
                continue
            occurred_at = self._parse_datetime(event.occurred_at)
            if occurred_at is None:
                continue
            if latest is None or occurred_at > latest:
                latest = occurred_at
        return latest

    @staticmethod
    def _is_quote_needed_status(service_request_status: str | None) -> bool:
        normalized = str(service_request_status or "").strip().casefold()
        if not normalized:
            return False
        return "quote needed" in normalized or normalized in {"needs quote", "quote"}

    @staticmethod
    def _quote_needed_subtype(service_request_status: str | None) -> str:
        normalized = str(service_request_status or "").strip().casefold()
        if any(token in normalized for token in ("landlord", "tenant")):
            return "landlord"
        if any(token in normalized for token in ("prepay", "pre-payment", "pre payment", "cod")):
            return "prepayment"
        return "customer"

    @staticmethod
    def _quote_needed_subtype_from_item(item: AttentionItemRecord) -> str:
        if item.stage != "quote_needed":
            return "customer"
        parts = item.item_id.rsplit(":", 1)
        if len(parts) == 2 and parts[1] in {"customer", "landlord", "prepayment"}:
            return parts[1]
        return "customer"

    @staticmethod
    def _quote_needed_details(service_request_status: str | None) -> str:
        normalized = str(service_request_status or "").strip()
        subtype = WorkflowStateService._quote_needed_subtype(service_request_status)
        if subtype == "landlord":
            return f"Current SR status is `{normalized or 'Quote Needed'}`. Landlord or tenant approval is blocking scheduling."
        if subtype == "prepayment":
            return f"Current SR status is `{normalized or 'Quote Needed'}`. COD or prepayment approval is blocking scheduling."
        return f"Current SR status is `{normalized or 'Quote Needed'}`. Customer quote approval is blocking scheduling."

    @staticmethod
    def _quote_needed_next_action(service_request_status: str | None) -> str:
        subtype = WorkflowStateService._quote_needed_subtype(service_request_status)
        if subtype == "landlord":
            return "Office should contact the landlord, confirm quote approval or prepayment, and then move the SR forward."
        if subtype == "prepayment":
            return "Office should confirm COD pricing or prepayment, collect approval, and then return the SR to scheduling."
        return "Dispatch or office should contact the customer, confirm the quote path, and capture approval before scheduling."

    @staticmethod
    def _triage_stage_label(stage: str | None) -> str:
        labels = {
            "new_sr_triage": "New SR Triage",
            "model_serial_needed": "Model/Serial Needed",
            "likely_parts_previsit": "Likely Parts Previsit",
            "diagnostic_required": "Diagnostic Required",
            "previsit_quote_needed": "Previsit Quote Needed",
        }
        return labels.get(stage or "", "Unknown Triage Stage")

    @staticmethod
    def _normalize_triage_disposition(disposition: str | None) -> str | None:
        candidate = str(disposition or "").strip().lower().replace(" ", "_").replace("-", "_")
        if candidate in {"schedule_normal", "collect_info", "parts_first", "diag_first", "quote_before_schedule"}:
            return candidate
        return None

    @staticmethod
    def _triage_stage_for_disposition(disposition: str | None) -> str | None:
        mapping = {
            "schedule_normal": None,
            "collect_info": "model_serial_needed",
            "parts_first": "likely_parts_previsit",
            "diag_first": "diagnostic_required",
            "quote_before_schedule": "previsit_quote_needed",
        }
        return mapping.get(disposition or "")

    @staticmethod
    def _triage_stage_from_status(service_request_status: str | None) -> str | None:
        normalized = str(service_request_status or "").strip().casefold()
        if not normalized:
            return None
        if "model" in normalized and "serial" in normalized:
            return "model_serial_needed"
        if "more info" in normalized or "need info" in normalized:
            return "model_serial_needed"
        if "parts/schedule" in normalized or "need parts/schedule" in normalized or "needs parts/schedule" in normalized:
            return "new_sr_triage"
        if "diagnostic required" in normalized or "diag required" in normalized:
            return "diagnostic_required"
        return None

    def _triage_disposition_for_reference(self, *, reference: str) -> str | None:
        normalized_reference = reference.strip().casefold()
        latest_event: WorkflowEventRecord | None = None
        for event in self.store.load().events:
            if event.event_type != "triage_disposition_set":
                continue
            if (event.reference or "").strip().casefold() != normalized_reference:
                continue
            if latest_event is None or (event.occurred_at or "") > (latest_event.occurred_at or ""):
                latest_event = event
        if latest_event is None:
            return None
        return self._normalize_triage_disposition(latest_event.metadata.get("disposition"))

    def _triage_first_seen_at(self, *, reference: str) -> str | None:
        normalized_reference = reference.strip().casefold()
        timestamps = [
            event.occurred_at
            for event in self.store.load().events
            if (event.reference or "").strip().casefold() == normalized_reference and event.event_type == "triage_disposition_set"
        ]
        valid = [value for value in timestamps if value]
        return min(valid) if valid else None

    @staticmethod
    def _triage_details(stage: str, service_request_status: str | None, user_details: str | None = None) -> str:
        status_text = str(service_request_status or "").strip() or "No explicit SR status detail"
        detail_map = {
            "new_sr_triage": "This SR needs a quick technical review before scheduling. Decide whether it should be parts-first, quote-blocked, or diagnostic-first.",
            "model_serial_needed": "Triage needs more intake detail before a first-time-fix plan is reliable. Collect model and serial information or clearer symptom detail.",
            "likely_parts_previsit": "Triage marked this SR as a strong parts-first candidate. Review likely failure path and decide whether to source parts before the first visit.",
            "diagnostic_required": "Triage marked this SR as diagnostic-first. The symptom path is too uncertain for previsit parts planning.",
            "previsit_quote_needed": "Quote, landlord approval, or prepayment should be resolved before this SR is scheduled.",
        }
        base = f"Current SR status is `{status_text}`. {detail_map.get(stage, '')}".strip()
        if user_details:
            return f"{base} {user_details}".strip()
        return base

    @staticmethod
    def _triage_next_action(stage: str) -> str:
        actions = {
            "new_sr_triage": "Review intake notes, decide diag-first versus parts-first, and record the triage disposition.",
            "model_serial_needed": "Office should collect model and serial information or better symptom detail before scheduling.",
            "likely_parts_previsit": "Triage or parts should review likely required parts and decide whether to order before the first visit.",
            "diagnostic_required": "Dispatch should book a diagnostic visit instead of assuming a parts-first fix path.",
            "previsit_quote_needed": "Office should resolve quote approval, landlord approval, or prepayment before scheduling.",
        }
        return actions.get(stage, "Review the SR and record the next triage decision.")

    @staticmethod
    def _find_existing_triage_item(items, *, reference: str) -> AttentionItemRecord | None:
        triage_stages = {
            "new_sr_triage",
            "model_serial_needed",
            "likely_parts_previsit",
            "diagnostic_required",
            "previsit_quote_needed",
        }
        normalized_reference = reference.strip().casefold()
        for item in items:
            if item.stage in triage_stages and item.reference.strip().casefold() == normalized_reference:
                return item
        return None

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
