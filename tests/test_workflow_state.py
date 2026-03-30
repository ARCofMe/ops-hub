"""Workflow-state service and store tests for Ops Hub."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ops_hub.models.requests import (
    AttentionItemRecord,
    BlueFolderJobSummary,
    PartRequestRecord,
    PartsCaseRecord,
    PartsLifecycleSnapshot,
    TechnicianMappingRecord,
    WorkflowStateSnapshot,
)
from ops_hub.services.dispatch import DispatchService
from ops_hub.services.notifications import NotificationService
from ops_hub.services.parts_request_store import PartsRequestStore
from ops_hub.services.workflow_state import WorkflowStateService
from ops_hub.services.workflow_state_store import WorkflowStateStore


class FakeBlueFolderService:
    def __init__(self) -> None:
        self.assignments_by_user = {
            13051: [
                {
                    "serviceRequestId": "100",
                    "subject": "Dryer repair",
                    "city": "Portland",
                    "state": "ME",
                    "routeLabel": "AM",
                }
            ]
        }
        self.snapshots = {
            100: PartsLifecycleSnapshot(
                stage="part_ready",
                stage_label="Ready for Scheduling",
                latest_status_text="All parts are in.",
                latest_status_author="Parts",
                latest_status_at="2026-03-22 10:00",
            )
        }

    async def get_assignments_for_user_today(self, user_id: int):
        return self.assignments_by_user.get(user_id, [])

    async def get_parts_snapshot(self, sr_id: int):
        return self.snapshots.get(sr_id)

    async def get_job_summary(self, reference: str, *, include_customer_contacts: bool = True):
        return BlueFolderJobSummary(
            reference=reference,
            available=True,
            integration_status="live_read",
            message="ok",
            service_request_id=reference.replace("SR-", ""),
            subject="Dryer repair",
            customer_name="Acme Customer",
            service_request_status="Scheduled",
        )

    def recommend_next_action(self, snapshot: PartsLifecycleSnapshot) -> str:
        return f"Schedule follow-up for {snapshot.stage_label}."


class FakePartsCannonService:
    def __init__(self) -> None:
        self.request_store = PartsRequestStore(
            file_path=None,
            records=[
                PartRequestRecord(
                    request_id=1,
                    reference="SR-100",
                    description="Need blower wheel",
                    requested_by_user_id=42,
                    technician_bluefolder_user_id=13051,
                    assigned_parts_user_id=77,
                    status="ordered",
                    created_at="2026-03-21T09:00:00+00:00",
                    updated_at="2026-03-21T12:00:00+00:00",
                )
            ],
        )


def test_workflow_state_store_round_trip(tmp_path: Path) -> None:
    store = WorkflowStateStore(file_path=tmp_path / "workflow-state.json")
    snapshot = WorkflowStateSnapshot(
        updated_at="2026-03-29T10:00:00+00:00",
        attention_items=[
            AttentionItemRecord(
                item_id="dispatch:SR-100:part_ready",
                sr_id=100,
                reference="SR-100",
                category="dispatch",
                status="open",
                stage="part_ready",
                stage_label="Ready for Scheduling",
                summary="Dryer repair",
            )
        ],
    )

    store.save(snapshot)
    loaded = store.load()

    assert loaded.updated_at == "2026-03-29T10:00:00+00:00"
    assert loaded.attention_items[0].reference == "SR-100"


def test_workflow_state_service_derives_attention_and_parts_cases() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
    )

    scanned_jobs, attention_items = asyncio.run(
        service.refresh_dispatch_attention(
            [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]
        )
    )

    snapshot = service.current_snapshot()

    assert scanned_jobs == 1
    assert len(attention_items) == 1
    assert attention_items[0].reference == "SR-100"
    assert attention_items[0].next_action == "Schedule follow-up for Ready for Scheduling."
    assert attention_items[0].age_bucket in {"stale", "urgent"}
    assert snapshot.parts_cases[0].reference == "SR-100"
    assert snapshot.parts_cases[0].open_request_ids == [1]
    assert snapshot.parts_cases[0].assigned_parts_user_id == 77


def test_workflow_state_service_filters_attention_by_age_and_owner() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
    )

    scanned_jobs, attention_items = asyncio.run(
        service.refresh_dispatch_attention(
            [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
            age_bucket="urgent",
            owner_discord_user_id=42,
        )
    )

    assert scanned_jobs == 1
    assert len(attention_items) == 1
    assert attention_items[0].age_bucket == "urgent"
    assert attention_items[0].owner_discord_user_id == 42


def test_workflow_state_service_derives_quote_needed_attention() -> None:
    bluefolder = FakeBlueFolderService()

    async def get_job_summary(reference: str, *, include_customer_contacts: bool = True):
        return BlueFolderJobSummary(
            reference=reference,
            available=True,
            integration_status="live_read",
            message="ok",
            service_request_id="100",
            subject="Dryer repair",
            customer_name="Acme Customer",
            service_request_status="Quote Needed",
        )

    bluefolder.get_job_summary = get_job_summary
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=bluefolder,
        parts_cannon_service=FakePartsCannonService(),
    )

    scanned_jobs, attention_items = asyncio.run(
        service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)])
    )

    quote_items = [item for item in attention_items if item.stage == "quote_needed"]

    assert scanned_jobs == 1
    assert len(quote_items) == 1
    assert quote_items[0].stage_label == "Quote Needed"
    assert "confirm the quote path" in (quote_items[0].next_action or "")
    assert quote_items[0].item_id.endswith(":customer")
    assert "Customer quote approval" in (quote_items[0].details or "")


def test_workflow_state_service_derives_landlord_quote_attention() -> None:
    bluefolder = FakeBlueFolderService()

    async def get_job_summary(reference: str, *, include_customer_contacts: bool = True):
        return BlueFolderJobSummary(
            reference=reference,
            available=True,
            integration_status="live_read",
            message="ok",
            service_request_id="100",
            subject="Dryer repair",
            customer_name="Acme Customer",
            service_request_status="Quote Needed - Landlord Approval",
        )

    bluefolder.get_job_summary = get_job_summary
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=bluefolder,
        parts_cannon_service=FakePartsCannonService(),
    )

    _, attention_items = asyncio.run(
        service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)])
    )

    quote_items = [item for item in attention_items if item.stage == "quote_needed"]

    assert len(quote_items) == 1
    assert quote_items[0].item_id.endswith(":landlord")
    assert "landlord" in (quote_items[0].next_action or "").casefold()
    assert "Landlord or tenant approval" in (quote_items[0].details or "")


def test_workflow_state_service_derives_prepayment_quote_attention() -> None:
    bluefolder = FakeBlueFolderService()

    async def get_job_summary(reference: str, *, include_customer_contacts: bool = True):
        return BlueFolderJobSummary(
            reference=reference,
            available=True,
            integration_status="live_read",
            message="ok",
            service_request_id="100",
            subject="Dryer repair",
            customer_name="Acme Customer",
            service_request_status="Quote Needed - COD Prepayment",
        )

    bluefolder.get_job_summary = get_job_summary
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=bluefolder,
        parts_cannon_service=FakePartsCannonService(),
    )

    _, attention_items = asyncio.run(
        service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)])
    )

    quote_items = [item for item in attention_items if item.stage == "quote_needed"]

    assert len(quote_items) == 1
    assert quote_items[0].item_id.endswith(":prepayment")
    assert "prepayment" in (quote_items[0].next_action or "").casefold()
    assert "COD or prepayment approval" in (quote_items[0].details or "")


def test_workflow_state_service_uses_stage_specific_sla_thresholds() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
    )

    assert service._age_bucket_for_stage("part_ready", 30) == "stale"
    assert service._age_bucket_for_stage("part_ready", 60) == "urgent"
    assert service._age_bucket_for_stage("part_received", 30) == "stale"
    assert service._age_bucket_for_stage("part_received", 60) == "stale"
    assert service._age_bucket_for_stage("part_received", 80) == "urgent"


def test_workflow_state_policy_cycle_sends_and_dedupes_urgent_notices() -> None:
    notifications = NotificationService()
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type(
            "DirectoryStub",
            (),
            {"mapping_records": lambda self: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]},
        )(),
        notification_service=notifications,
    )

    first = asyncio.run(service.run_policy_cycle())
    second = asyncio.run(service.run_policy_cycle())

    assert first["urgent_items"] == 1
    assert first["owner_gap_urgent_items"] == 1
    assert first["notices_sent"] == 1
    assert first["topics_count"] == 1
    assert second["notices_sent"] == 0
    assert len(notifications.records) == 1
    assert notifications.records[0].topic == "dispatch.scheduling_attention.owner_gap"


def test_workflow_state_policy_cycle_routes_reopened_urgent_items_separately() -> None:
    notifications = NotificationService()
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type(
            "DirectoryStub",
            (),
            {
                "mapping_records": lambda self: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
                "discord_mention": lambda self, user_id: f"<@{user_id}>",
            },
        )(),
        notification_service=notifications,
    )

    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    service.reopen_attention(sr_id=100, stage="part_ready", actor_user_id=77)
    summary = asyncio.run(service.run_policy_cycle())

    assert summary["urgent_items"] == 1
    assert summary["reopened_urgent_items"] == 1
    assert summary["owner_gap_urgent_items"] == 1
    assert summary["notices_sent"] == 1
    assert notifications.records[0].topic == "dispatch.scheduling_attention.reopened.owner_gap"


def test_workflow_state_policy_cycle_reminds_on_long_suppressed_urgent_items() -> None:
    notifications = NotificationService()
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type(
            "DirectoryStub",
            (),
            {
                "mapping_records": lambda self: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
                "discord_mention": lambda self, user_id: f"<@{user_id}>",
            },
        )(),
        notification_service=notifications,
    )

    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    service.acknowledge_attention(sr_id=100, stage="part_ready", actor_user_id=77)
    snapshot = service.current_snapshot()
    snapshot.events[-1].occurred_at = "2026-03-20T10:00:00+00:00"
    service.store.save(snapshot)

    first = asyncio.run(service.run_policy_cycle())
    second = asyncio.run(service.run_policy_cycle())

    assert first["urgent_items"] == 0
    assert first["suppressed_urgent_items"] == 1
    assert first["suppressed_reminders_sent"] == 1
    assert notifications.records[0].topic == "dispatch.scheduling_attention.suppressed"
    assert second["suppressed_reminders_sent"] == 0


def test_workflow_state_actions_persist_across_refresh_and_suppress_policy() -> None:
    notifications = NotificationService()
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type(
            "DirectoryStub",
            (),
            {
                "mapping_records": lambda self: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
                "discord_mention": lambda self, user_id: f"<@{user_id}>",
            },
        )(),
        notification_service=notifications,
    )

    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    assigned = service.assign_attention_owner(sr_id=100, stage="part_ready", assigned_owner_discord_user_id=99, actor_user_id=77)
    assert assigned.assigned_owner_discord_user_id == 99
    snoozed = service.snooze_attention(sr_id=100, stage="part_ready", hours=4, actor_user_id=77)
    assert snoozed.status == "snoozed"

    first = asyncio.run(service.run_policy_cycle())
    refreshed = service.current_snapshot().attention_items[0]

    assert refreshed.status == "snoozed"
    assert refreshed.assigned_owner_discord_user_id == 99
    assert first["urgent_items"] == 0
    assert first["notices_sent"] == 0
    assert notifications.records == []


def test_workflow_state_acknowledge_marks_item_and_suppresses_policy() -> None:
    notifications = NotificationService()
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type(
            "DirectoryStub",
            (),
            {
                "mapping_records": lambda self: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
                "discord_mention": lambda self, user_id: f"<@{user_id}>",
            },
        )(),
        notification_service=notifications,
    )

    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    acknowledged = service.acknowledge_attention(sr_id=100, stage="part_ready", actor_user_id=77)
    summary = asyncio.run(service.run_policy_cycle())

    assert acknowledged.status == "acknowledged"
    assert acknowledged.acknowledged_by_user_id == 77
    assert summary["urgent_items"] == 0
    assert summary["notices_sent"] == 0
    assert notifications.records == []


def test_workflow_state_lifecycle_controls_restore_open_attention_and_history() -> None:
    notifications = NotificationService()
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type(
            "DirectoryStub",
            (),
            {
                "mapping_records": lambda self: [TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)],
                "discord_mention": lambda self, user_id: f"<@{user_id}>",
            },
        )(),
        notification_service=notifications,
    )

    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    service.assign_attention_owner(sr_id=100, stage="part_ready", assigned_owner_discord_user_id=99, actor_user_id=77)
    service.clear_attention_owner(sr_id=100, stage="part_ready", actor_user_id=77)
    service.snooze_attention(sr_id=100, stage="part_ready", hours=4, actor_user_id=77)
    service.unsnooze_attention(sr_id=100, stage="part_ready", actor_user_id=77)
    service.acknowledge_attention(sr_id=100, stage="part_ready", actor_user_id=77)
    reopened = service.reopen_attention(sr_id=100, stage="part_ready", actor_user_id=77)
    summary = asyncio.run(service.run_policy_cycle())
    history = service.describe_attention_history(sr_id=100, stage="part_ready")

    assert reopened.status == "open"
    assert reopened.acknowledged_at is None
    assert reopened.snoozed_until is None
    assert summary["urgent_items"] == 1
    assert summary["notices_sent"] == 1
    assert "attention_reopened" in history.message
    assert "attention_unsnoozed" in history.message
    assert "attention_owner_cleared" in history.message


def test_workflow_state_policy_topics_vary_by_queue_type() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
    )

    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="1",
            sr_id=100,
            reference="SR-100",
            category="dispatch",
            status="open",
            stage="part_ready",
            stage_label="Ready for Scheduling",
            summary="Dryer repair",
        )
    ) == "dispatch.scheduling_attention"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="2",
            sr_id=101,
            reference="SR-101",
            category="dispatch",
            status="open",
            stage="issue_reported",
            stage_label="Issue Reported",
            summary="Washer repair",
        )
    ) == "dispatch.parts_issue_attention"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="3",
            sr_id=102,
            reference="SR-102",
            category="dispatch",
            status="open",
            stage="part_received",
            stage_label="Received",
            summary="Oven repair",
        )
    ) == "parts.received_attention"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="4",
            sr_id=103,
            reference="SR-103",
            category="dispatch",
            status="open",
            stage="part_ready",
            stage_label="Ready for Scheduling",
            summary="Range repair",
        ),
        qualifiers=("reopened",),
    ) == "dispatch.scheduling_attention.reopened"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="5",
            sr_id=104,
            reference="SR-104",
            category="dispatch",
            status="acknowledged",
            stage="part_ready",
            stage_label="Ready for Scheduling",
            summary="Fridge repair",
        ),
        qualifiers=("suppressed",),
    ) == "dispatch.scheduling_attention.suppressed"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="6",
            sr_id=105,
            reference="SR-105",
            category="dispatch",
            status="open",
            stage="part_ready",
            stage_label="Ready for Scheduling",
            summary="Microwave repair",
        ),
        qualifiers=("reopened", "owner_gap"),
    ) == "dispatch.scheduling_attention.reopened.owner_gap"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="7",
            sr_id=106,
            reference="SR-106",
            category="dispatch",
            status="open",
            stage="quote_needed",
            stage_label="Quote Needed",
            summary="Dishwasher repair",
        ),
    ) == "dispatch.quote_needed_attention"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="8:landlord",
            sr_id=107,
            reference="SR-107",
            category="dispatch",
            status="open",
            stage="quote_needed",
            stage_label="Quote Needed",
            summary="Oven repair",
        ),
    ) == "dispatch.quote_needed_attention.landlord"
    assert service._policy_topic_for_item(
        AttentionItemRecord(
            item_id="9:prepayment",
            sr_id=108,
            reference="SR-108",
            category="dispatch",
            status="open",
            stage="quote_needed",
            stage_label="Quote Needed",
            summary="Range repair",
        ),
        qualifiers=("owner_gap",),
    ) == "dispatch.quote_needed_attention.prepayment.owner_gap"


def test_workflow_state_service_builds_service_request_timeline() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
    )
    service.record_event(
        event_type="start",
        source="bluefolder.field",
        sr_id=100,
        summary="Technician started work.",
        actor_label="Tech 42",
        occurred_at="2026-03-22T08:00:00+00:00",
    )

    timeline = asyncio.run(service.build_service_request_timeline(100))

    assert timeline.reference == "SR-100"
    assert len(timeline.entries) >= 3
    assert any(entry.summary == "Technician started work." for entry in timeline.entries)
    assert any("Tracked parts request 1 is ordered." == entry.summary for entry in timeline.entries)
    assert any("Parts status moved to Ready for Scheduling." == entry.summary for entry in timeline.entries)


class FakeWorkflowStateService:
    async def refresh_dispatch_attention(self, mappings, *, stage_filter=None, technician_bluefolder_user_id=None, age_bucket=None, owner_discord_user_id=None):
        return 1, [
            AttentionItemRecord(
                item_id="dispatch:SR-100:part_ready",
                sr_id=100,
                reference="SR-100",
                category="dispatch",
                status="snoozed",
                stage="part_ready",
                stage_label="Ready for Scheduling",
                summary="Dryer repair",
                location="Portland ME",
                route_label="AM",
                owner_discord_user_id=42,
                owner_bluefolder_user_id=13051,
                assigned_owner_discord_user_id=99,
                next_action="Schedule the return visit.",
                age_hours=80,
                age_bucket="urgent",
                snoozed_until="2026-03-29T12:00:00+00:00",
                acknowledged_by_user_id=77,
            )
        ]

    def current_snapshot(self):
        return WorkflowStateSnapshot(
            parts_cases=[
                PartsCaseRecord(
                    case_id="SR-100",
                    reference="SR-100",
                    sr_id=100,
                    stage="part_ready",
                    stage_label="Ready for Scheduling",
                    status="open",
                    open_request_ids=[1],
                    next_action="Schedule the return visit.",
                    updated_at="2026-03-29T10:00:00+00:00",
                    age_hours=80,
                    age_bucket="urgent",
                )
            ]
        )

    def attention_metrics(self, snapshot=None):
        return {
            "total_items": 1,
            "status_counts": {"snoozed": 1},
            "stage_counts": {"Ready for Scheduling": 1},
            "age_counts": {"urgent": 1},
            "assigned_owner_items": 1,
            "unassigned_owner_items": 0,
            "urgent_open_items": 0,
            "urgent_suppressed_items": 1,
        }


def test_dispatch_service_uses_workflow_state_attention_items() -> None:
    class DispatchBlueFolderStub:
        async def get_assignments_for_user_today(self, user_id: int):
            return [{"serviceRequestId": "100", "subject": "Dryer repair"}] if user_id == 13051 else []

        async def get_user_name(self, user_id: int) -> str:
            return f"Tech {user_id}"

    service = DispatchService(
        adapter=object(),
        bluefolder_service=DispatchBlueFolderStub(),
        workflow_state_service=FakeWorkflowStateService(),
    )

    result = asyncio.run(
        service.lookup_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)])
    )

    assert "**Dispatch Attention**" in result.message
    assert "Attention jobs: `1`" in result.message
    assert "`SR-100` Dryer repair" in result.message
    assert "Next action: Schedule the return visit." in result.message
    assert "Age: `urgent` (80h)" in result.message
    assert "Follow-up owner: <@99>" in result.message
    assert "Status: `snoozed`" in result.message


def test_dispatch_board_uses_workflow_state_queues() -> None:
    class DispatchAdapterStub:
        async def get_user_assignments_today(self, user_id: int):
            return [{"serviceRequestId": "100", "subject": "Dryer repair"}] if user_id == 13051 else []

        async def get_assignments_for_user(self, user_id: int):
            return []

        async def get_origin_for_user(self, user_id: int):
            return "South Paris, ME"

    class DispatchBlueFolderStub:
        async def get_assignments_for_user_today(self, user_id: int):
            return [{"serviceRequestId": "100", "subject": "Dryer repair"}] if user_id == 13051 else []

        async def get_user_name(self, user_id: int) -> str:
            return f"Tech {user_id}"

    service = DispatchService(
        adapter=DispatchAdapterStub(),
        bluefolder_service=DispatchBlueFolderStub(),
        workflow_state_service=FakeWorkflowStateService(),
    )

    result = asyncio.run(
        service.lookup_dispatch_board(
            [
                TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051),
                TechnicianMappingRecord(discord_user_id=43, bluefolder_user_id=13052),
            ]
        )
    )

    assert "**Attention Queues**" in result.message
    assert "Ready for Scheduling: `1`" in result.message
    assert "**Queue Status**" in result.message
    assert "snoozed: `1`" in result.message
    assert "Assigned follow-up owners: `1`" in result.message
    assert "**Age Buckets**" in result.message
    assert "urgent: `1`" in result.message
    assert "**Urgent State**" in result.message
    assert "Suppressed urgent: `1`" in result.message
    assert "**Open Parts Cases**" in result.message
    assert "Tracked requests: `1`" in result.message
    assert "**Technician Load**" in result.message


def test_dispatch_service_attention_actions_use_workflow_state() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type("DirectoryStub", (), {"discord_mention": lambda self, user_id: f"<@{user_id}>"})(),
    )
    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    dispatch = DispatchService(
        adapter=object(),
        bluefolder_service=FakeBlueFolderService(),
        workflow_state_service=service,
        technician_directory_service=type("DirectoryStub", (), {"discord_mention": lambda self, user_id: f"<@{user_id}>", "reverse_mappings": lambda self: {13051: 42}})(),
    )

    assigned = asyncio.run(
        dispatch.assign_dispatch_attention_owner(
            sr_id=100,
            stage="part_ready",
            assigned_owner_discord_user_id=99,
            actor_user_id=77,
        )
    )
    snoozed = asyncio.run(
        dispatch.snooze_dispatch_attention(
            sr_id=100,
            stage="part_ready",
            hours=4,
            actor_user_id=77,
        )
    )
    acknowledged = asyncio.run(
        dispatch.acknowledge_dispatch_attention(
            sr_id=100,
            stage="part_ready",
            actor_user_id=77,
        )
    )

    assert "**Assigned owner Attention Item**" in assigned.message
    assert "Follow-up owner: <@99>" in assigned.message
    assert "**Snoozed Attention Item**" in snoozed.message
    assert "Snoozed until:" in snoozed.message
    assert "**Acknowledged Attention Item**" in acknowledged.message
    assert "Status: `acknowledged`" in acknowledged.message


def test_dispatch_service_attention_lifecycle_and_history_use_workflow_state() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
        technician_directory_service=type("DirectoryStub", (), {"discord_mention": lambda self, user_id: f"<@{user_id}>", "mapping_records": lambda self: []})(),
    )
    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    dispatch = DispatchService(
        adapter=object(),
        bluefolder_service=FakeBlueFolderService(),
        workflow_state_service=service,
        technician_directory_service=type("DirectoryStub", (), {"discord_mention": lambda self, user_id: f"<@{user_id}>", "reverse_mappings": lambda self: {13051: 42}})(),
    )

    asyncio.run(dispatch.assign_dispatch_attention_owner(sr_id=100, stage="part_ready", assigned_owner_discord_user_id=99, actor_user_id=77))
    cleared = asyncio.run(dispatch.clear_dispatch_attention_owner(sr_id=100, stage="part_ready", actor_user_id=77))
    asyncio.run(dispatch.snooze_dispatch_attention(sr_id=100, stage="part_ready", hours=4, actor_user_id=77))
    unsnoozed = asyncio.run(dispatch.unsnooze_dispatch_attention(sr_id=100, stage="part_ready", actor_user_id=77))
    asyncio.run(dispatch.acknowledge_dispatch_attention(sr_id=100, stage="part_ready", actor_user_id=77))
    reopened = asyncio.run(dispatch.reopen_dispatch_attention(sr_id=100, stage="part_ready", actor_user_id=77))
    history = asyncio.run(dispatch.describe_dispatch_attention_history(sr_id=100, stage="part_ready"))

    assert "**Cleared owner Attention Item**" in cleared.message
    assert "Status: `open`" in unsnoozed.message
    assert "**Reopened Attention Item**" in reopened.message
    assert "**Attention History SR-100**" in history.message
    assert "attention_reopened" in history.message


def test_workflow_state_attention_metrics_report_status_and_urgency() -> None:
    service = WorkflowStateService(
        store=WorkflowStateStore(file_path=None),
        bluefolder_service=FakeBlueFolderService(),
        parts_cannon_service=FakePartsCannonService(),
    )
    asyncio.run(service.refresh_dispatch_attention([TechnicianMappingRecord(discord_user_id=42, bluefolder_user_id=13051)]))
    service.assign_attention_owner(sr_id=100, stage="part_ready", assigned_owner_discord_user_id=99, actor_user_id=77)
    service.snooze_attention(sr_id=100, stage="part_ready", hours=4, actor_user_id=77)

    metrics = service.attention_metrics()

    assert metrics["total_items"] == 1
    assert metrics["status_counts"] == {"snoozed": 1}
    assert metrics["assigned_owner_items"] == 1
    assert metrics["urgent_open_items"] == 0
    assert metrics["urgent_suppressed_items"] == 1
