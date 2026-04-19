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

