"""Complaint Intelligence integration tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3

from ops_hub.services.complaint_intelligence import ComplaintIntelligenceService


def test_complaint_intelligence_reports_unconfigured() -> None:
    service = ComplaintIntelligenceService()

    payload = asyncio.run(service.get_service_request_payload(sr_id=123))

    assert payload["available"] is False
    assert payload["integrationStatus"] == "unconfigured"


def test_complaint_intelligence_returns_sr_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "complaint_intelligence.db"
    _build_db(db_path)
    service = ComplaintIntelligenceService(database_url=f"sqlite:///{db_path}")

    payload = asyncio.run(service.get_service_request_payload(sr_id=1001))

    assert payload["available"] is True
    assert payload["request"]["modelNumber"] == "RF1"
    assert payload["complaintTags"] == [{"tag": "no_cool", "confidence": 1.0, "source": "rules"}]
    assert payload["similarRequestCount"] == 2
    assert payload["recommendations"][0]["item"] == "FAN-1"
    assert payload["recommendations"][0]["score"] == 1.0
    assert payload["modelFamilyTrends"]["modelFamily"] == "RF1"
    assert payload["feedbackSummary"]["counts"] == {}
    assert payload["feedbackHealth"]["status"] == "no_feedback"
    assert payload["evidencePacket"]["version"] == "evidence.v1"
    assert payload["evidencePacket"]["confidence"] == "limited"
    assert payload["evidencePacket"]["classification"]["complaintTags"] == ["no_cool"]
    assert payload["evidencePacket"]["rankedParts"][0]["item"] == "FAN-1"
    assert payload["evidencePacket"]["supportingEvidence"][0]["serviceRequestId"] == "1001"
    assert any("evaporator fan" in question.lower() for question in payload["evidencePacket"]["diagnosticQuestions"])


def test_complaint_intelligence_uses_live_context_when_sr_not_ingested(tmp_path: Path) -> None:
    db_path = tmp_path / "complaint_intelligence.db"
    _build_db(db_path)
    service = ComplaintIntelligenceService(database_url=f"sqlite:///{db_path}")

    payload = asyncio.run(
        service.get_service_request_payload(
            sr_id=9999,
            current_context={
                "complaintText": "Customer says refrigerator is not cooling",
                "modelNumber": "RF1",
                "brand": "Samsung",
                "applianceType": "refrigerator",
            },
        )
    )

    assert payload["available"] is True
    assert payload["integrationStatus"] == "live_context"
    assert payload["feedbackCaptureEnabled"] is False
    assert payload["similarRequestCount"] == 2
    assert payload["recommendations"][0]["item"] == "FAN-1"
    assert payload["evidencePacket"]["classification"]["matchScope"] == "exact_model"


def test_complaint_intelligence_records_feedback(tmp_path: Path) -> None:
    db_path = tmp_path / "complaint_intelligence.db"
    _build_db(db_path)
    service = ComplaintIntelligenceService(database_url=f"sqlite:///{db_path}")

    result = asyncio.run(
        service.record_feedback(
            sr_id=1001,
            outcome="helpful",
            actor_user_id=42,
            source="ops_hub.routedesk",
            recommended_item="FAN-1",
            notes="Matched final repair.",
        )
    )
    payload = asyncio.run(service.get_service_request_payload(sr_id=1001))

    assert result["outcome"] == "helpful"
    assert payload["feedbackSummary"]["counts"]["helpful"] == 1
    assert payload["feedbackSummary"]["latest"]["recommendedItem"] == "FAN-1"
    assert payload["feedbackHealth"]["status"] == "supportive"
    assert payload["recommendations"][0]["feedbackWeight"]["helpful"] == 1
    assert payload["recommendations"][0]["baseScore"] == 1.0


def test_complaint_intelligence_trims_feedback_inputs(tmp_path: Path) -> None:
    db_path = tmp_path / "complaint_intelligence.db"
    _build_db(db_path)
    service = ComplaintIntelligenceService(database_url=f"sqlite:///{db_path}")

    asyncio.run(
        service.record_feedback(
            sr_id=1001,
            outcome="needs_review",
            actor_user_id=42,
            source="x" * 80,
            recommended_item="PART-" + ("A" * 200),
            notes="n" * 1200,
        )
    )
    payload = asyncio.run(service.get_service_request_payload(sr_id=1001))

    latest = payload["feedbackSummary"]["latest"]
    assert latest["source"] == "x" * 64
    assert len(latest["recommendedItem"]) == 128
    assert len(latest["notes"]) == 1000


def test_complaint_intelligence_dashboard_and_review_queue(tmp_path: Path) -> None:
    db_path = tmp_path / "complaint_intelligence.db"
    _build_db(db_path)
    service = ComplaintIntelligenceService(database_url=f"sqlite:///{db_path}")

    asyncio.run(
        service.record_feedback(
            sr_id=1001,
            outcome="not_helpful",
            actor_user_id=42,
            source="ops_hub.routedesk",
            recommended_item="FAN-1",
            notes="Did not match final repair.",
        )
    )

    dashboard = asyncio.run(service.get_dashboard_payload())
    queue = asyncio.run(service.get_feedback_review_queue())

    assert dashboard["available"] is True
    assert dashboard["feedbackVolume"] == 1
    assert dashboard["reviewQueueCount"] == 1
    assert dashboard["weakRecommendations"][0]["recommendedItem"] == "FAN-1"
    assert queue["available"] is True
    assert queue["items"][0]["serviceRequestId"] == "1001"
    assert queue["items"][0]["outcome"] == "not_helpful"


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE service_requests (
                id INTEGER PRIMARY KEY,
                service_request_id TEXT UNIQUE,
                completed_at TEXT,
                model_number TEXT,
                brand TEXT,
                appliance_type TEXT,
                complaint_text TEXT,
                resolution_notes TEXT
            );
            CREATE TABLE complaint_tags (
                id INTEGER PRIMARY KEY,
                service_request_pk INTEGER,
                tag TEXT,
                confidence REAL,
                source TEXT
            );
            CREATE TABLE billed_items (
                id INTEGER PRIMARY KEY,
                service_request_pk INTEGER,
                item_type TEXT,
                description TEXT,
                quantity REAL,
                amount REAL,
                sku TEXT
            );
            """
        )
        for pk, sr_id in [(1, "1001"), (2, "1002")]:
            conn.execute(
                """
                INSERT INTO service_requests
                    (id, service_request_id, completed_at, model_number, brand, appliance_type, complaint_text, resolution_notes)
                VALUES (?, ?, '2026-04-01', 'RF1', 'Samsung', 'refrigerator', 'not cooling', 'Replaced fan')
                """,
                (pk, sr_id),
            )
            conn.execute(
                "INSERT INTO complaint_tags (service_request_pk, tag, confidence, source) VALUES (?, 'no_cool', 1.0, 'rules')",
                (pk,),
            )
            conn.execute(
                """
                INSERT INTO billed_items (service_request_pk, item_type, description, quantity, amount, sku)
                VALUES (?, 'part', 'Evaporator fan', 1, 100, 'FAN-1')
                """,
                (pk,),
            )
