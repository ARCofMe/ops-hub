"""Read-only Complaint Intelligence integration for Ops Hub."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from urllib.parse import unquote


@dataclass(slots=True)
class ComplaintIntelligenceService:
    """Query normalized complaint intelligence data for RouteDesk decision support."""

    database_url: str | None = None
    project_path: str | None = None

    async def get_service_request_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return complaint intelligence for one service request id."""
        if not (self.database_url or "").strip():
            return self._unavailable(
                sr_id=sr_id,
                status="unconfigured",
                message="Complaint Intelligence database is not configured.",
            )

        db_path = self._sqlite_path(self.database_url or "")
        if db_path is None:
            return self._unavailable(
                sr_id=sr_id,
                status="unsupported_database",
                message="Only SQLite Complaint Intelligence databases are supported by this Ops Hub integration today.",
            )
        if not db_path.exists():
            return self._unavailable(
                sr_id=sr_id,
                status="missing_database",
                message="Complaint Intelligence database file does not exist.",
            )

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                request = self._fetch_request(conn, sr_id)
                if request is None:
                    return self._unavailable(
                        sr_id=sr_id,
                        status="not_found",
                        message=f"No Complaint Intelligence record is available for SR {sr_id}.",
                    )
                tags = self._fetch_tags(conn, request["id"])
                billed_items = self._fetch_billed_items(conn, request["id"])
                similar = self._fetch_similar_requests(conn, request, tags)
                recommendations = self._fetch_recommendations(conn, similar)
                common_resolutions = self._fetch_common_resolutions(conn, similar)
                model_family_trends = self._fetch_model_family_trends(conn, request)
                feedback_summary = self._fetch_feedback_summary(conn, request["id"])
                evidence_packet = self._build_evidence_packet(
                    request=request,
                    tags=tags,
                    similar=similar,
                    recommendations=recommendations,
                )
        except sqlite3.Error as exc:
            return self._unavailable(
                sr_id=sr_id,
                status="query_failed",
                message=f"Complaint Intelligence query failed: {exc}",
            )

        return {
            "success": True,
            "available": True,
            "integrationStatus": "ok",
            "message": "Complaint Intelligence record found.",
            "srId": str(sr_id),
            "sourcePath": str(Path(self.project_path).expanduser()) if self.project_path else None,
            "request": {
                "serviceRequestId": request["service_request_id"],
                "completedAt": request["completed_at"],
                "modelNumber": request["model_number"],
                "brand": request["brand"],
                "applianceType": request["appliance_type"],
                "complaintText": request["complaint_text"],
                "resolutionNotes": request["resolution_notes"],
            },
            "complaintTags": tags,
            "billedItems": billed_items,
            "similarRequestCount": len(similar),
            "recommendations": recommendations,
            "commonResolutions": common_resolutions,
            "modelFamilyTrends": model_family_trends,
            "feedbackSummary": feedback_summary,
            "feedbackCaptureEnabled": True,
            "evidencePacket": evidence_packet,
        }

    async def record_feedback(
        self,
        *,
        sr_id: int,
        outcome: str,
        actor_user_id: int | None,
        source: str,
        recommended_item: str | None = None,
        notes: str | None = None,
    ) -> dict[str, object]:
        """Persist operator feedback for one SR evidence view."""
        normalized_outcome = _normalize_feedback_outcome(outcome)
        if normalized_outcome is None:
            raise ValueError("Feedback outcome must be one of `helpful`, `not_helpful`, or `needs_review`.")

        db_path = self._sqlite_path(self.database_url or "")
        if db_path is None or not db_path.exists():
            raise ValueError("Complaint Intelligence feedback requires a local SQLite database.")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_feedback_table(conn)
                request = self._fetch_request(conn, sr_id)
                if request is None:
                    raise ValueError(f"No Complaint Intelligence record is available for SR {sr_id}.")
                conn.execute(
                    """
                    INSERT INTO recommendation_feedback (
                        service_request_pk, outcome, actor_user_id, source, recommended_item, notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(request["id"]),
                        normalized_outcome,
                        actor_user_id,
                        source,
                        _clean_optional(recommended_item),
                        _clean_optional(notes),
                    ),
                )
                conn.commit()
                feedback_summary = self._fetch_feedback_summary(conn, request["id"])
        except sqlite3.Error as exc:
            raise ValueError(f"Complaint Intelligence feedback write failed: {exc}") from exc

        return {
            "success": True,
            "srId": str(sr_id),
            "outcome": normalized_outcome,
            "feedbackSummary": feedback_summary,
            "message": f"Recorded Complaint Intelligence feedback as {normalized_outcome.replace('_', ' ')}.",
        }

    @staticmethod
    def _fetch_request(conn: sqlite3.Connection, sr_id: int) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT id, service_request_id, completed_at, model_number, brand, appliance_type, complaint_text, resolution_notes
            FROM service_requests
            WHERE service_request_id = ?
            """,
            (str(sr_id),),
        ).fetchone()

    @staticmethod
    def _fetch_tags(conn: sqlite3.Connection, service_request_pk: int) -> list[dict[str, object]]:
        rows = conn.execute(
            """
            SELECT tag, confidence, source
            FROM complaint_tags
            WHERE service_request_pk = ?
            ORDER BY tag
            """,
            (service_request_pk,),
        ).fetchall()
        return [
            {
                "tag": row["tag"],
                "confidence": row["confidence"],
                "source": row["source"],
            }
            for row in rows
        ]

    @staticmethod
    def _fetch_billed_items(conn: sqlite3.Connection, service_request_pk: int) -> list[dict[str, object]]:
        rows = conn.execute(
            """
            SELECT item_type, description, quantity, amount, sku
            FROM billed_items
            WHERE service_request_pk = ?
            ORDER BY item_type, COALESCE(sku, description)
            """,
            (service_request_pk,),
        ).fetchall()
        return [
            {
                "itemType": row["item_type"],
                "description": row["description"],
                "quantity": row["quantity"],
                "amount": row["amount"],
                "sku": row["sku"],
            }
            for row in rows
        ]

    @staticmethod
    def _fetch_similar_requests(
        conn: sqlite3.Connection,
        request: sqlite3.Row,
        tags: list[dict[str, object]],
    ) -> list[sqlite3.Row]:
        tag_values = [str(tag["tag"]) for tag in tags if tag.get("tag")]
        if not tag_values:
            return []
        placeholders = ",".join("?" for _ in tag_values)
        return conn.execute(
            f"""
            SELECT DISTINCT sr.id, sr.service_request_id, sr.completed_at, sr.model_number, sr.brand, sr.appliance_type,
                   sr.complaint_text, sr.resolution_notes
            FROM service_requests sr
            JOIN complaint_tags ct ON ct.service_request_pk = sr.id
            WHERE ct.tag IN ({placeholders})
              AND (? IS NULL OR sr.model_number = ?)
              AND (? IS NULL OR sr.brand = ?)
              AND (? IS NULL OR sr.appliance_type = ?)
            ORDER BY sr.completed_at DESC
            LIMIT 25
            """,
            tag_values
            + [
                request["model_number"],
                request["model_number"],
                request["brand"],
                request["brand"],
                request["appliance_type"],
                request["appliance_type"],
            ],
        ).fetchall()

    @staticmethod
    def _fetch_recommendations(conn: sqlite3.Connection, similar: list[sqlite3.Row]) -> list[dict[str, object]]:
        if not similar:
            return []
        ids = [row["id"] for row in similar]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(sku, ''), description) AS item, item_type,
                   COUNT(*) AS seen_count,
                   COUNT(DISTINCT service_request_pk) AS matching_request_count
            FROM billed_items
            WHERE service_request_pk IN ({placeholders})
              AND item_type != 'labor'
            GROUP BY COALESCE(NULLIF(sku, ''), description), item_type
            ORDER BY matching_request_count DESC, item ASC
            LIMIT 10
            """,
            ids,
        ).fetchall()
        denominator = max(len(ids), 1)
        return [
            {
                "item": row["item"],
                "itemType": row["item_type"],
                "seenCount": row["seen_count"],
                "matchingRequestCount": row["matching_request_count"],
                "score": round(float(row["matching_request_count"]) / denominator, 4),
            }
            for row in rows
        ]

    @staticmethod
    def _fetch_common_resolutions(conn: sqlite3.Connection, similar: list[sqlite3.Row]) -> list[str]:
        if not similar:
            return []
        ids = [row["id"] for row in similar]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""
            SELECT resolution_notes
            FROM service_requests
            WHERE id IN ({placeholders})
              AND resolution_notes IS NOT NULL
              AND resolution_notes != ''
            GROUP BY resolution_notes
            ORDER BY COUNT(*) DESC, resolution_notes ASC
            LIMIT 5
            """,
            ids,
        ).fetchall()
        return [str(row["resolution_notes"]) for row in rows]

    @staticmethod
    def _fetch_model_family_trends(conn: sqlite3.Connection, request: sqlite3.Row) -> dict[str, object] | None:
        model_family = _model_family_prefix(request["model_number"])
        if model_family is None:
            return None
        rows = conn.execute(
            """
            SELECT sr.id
            FROM service_requests sr
            WHERE sr.model_number IS NOT NULL
              AND REPLACE(REPLACE(REPLACE(UPPER(sr.model_number), '-', ''), '/', ''), '.', '') LIKE ?
            ORDER BY sr.completed_at DESC
            LIMIT 100
            """,
            (f"{model_family}%",),
        ).fetchall()
        request_ids = [int(row["id"]) for row in rows]
        if not request_ids:
            return None
        placeholders = ",".join("?" for _ in request_ids)
        complaint_rows = conn.execute(
            f"""
            SELECT ct.tag, COUNT(*) AS tag_count
            FROM complaint_tags ct
            WHERE ct.service_request_pk IN ({placeholders})
            GROUP BY ct.tag
            ORDER BY tag_count DESC, ct.tag ASC
            LIMIT 5
            """,
            request_ids,
        ).fetchall()
        part_rows = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(bi.sku, ''), bi.description) AS item, bi.item_type, COUNT(DISTINCT bi.service_request_pk) AS seen_count
            FROM billed_items bi
            WHERE bi.service_request_pk IN ({placeholders})
              AND bi.item_type != 'labor'
            GROUP BY COALESCE(NULLIF(bi.sku, ''), bi.description), bi.item_type
            ORDER BY seen_count DESC, item ASC
            LIMIT 5
            """,
            request_ids,
        ).fetchall()
        return {
            "modelFamily": model_family,
            "requestCount": len(request_ids),
            "topComplaintTags": [{"tag": row["tag"], "count": row["tag_count"]} for row in complaint_rows],
            "topParts": [{"item": row["item"], "itemType": row["item_type"], "count": row["seen_count"]} for row in part_rows],
        }

    @staticmethod
    def _fetch_feedback_summary(conn: sqlite3.Connection, service_request_pk: int) -> dict[str, object]:
        ComplaintIntelligenceService._ensure_feedback_table(conn)
        rows = conn.execute(
            """
            SELECT outcome, COUNT(*) AS feedback_count, MAX(created_at) AS last_created_at
            FROM recommendation_feedback
            WHERE service_request_pk = ?
            GROUP BY outcome
            ORDER BY outcome ASC
            """,
            (service_request_pk,),
        ).fetchall()
        counts = {str(row["outcome"]): int(row["feedback_count"]) for row in rows}
        latest = conn.execute(
            """
            SELECT outcome, source, recommended_item, notes, actor_user_id, created_at
            FROM recommendation_feedback
            WHERE service_request_pk = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (service_request_pk,),
        ).fetchone()
        return {
            "counts": counts,
            "latest": (
                {
                    "outcome": latest["outcome"],
                    "source": latest["source"],
                    "recommendedItem": latest["recommended_item"],
                    "notes": latest["notes"],
                    "actorUserId": latest["actor_user_id"],
                    "createdAt": latest["created_at"],
                }
                if latest is not None
                else None
            ),
        }

    @staticmethod
    def _ensure_feedback_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_feedback (
                id INTEGER PRIMARY KEY,
                service_request_pk INTEGER NOT NULL REFERENCES service_requests(id),
                outcome VARCHAR(32) NOT NULL,
                actor_user_id INTEGER,
                source VARCHAR(64) NOT NULL,
                recommended_item VARCHAR(128),
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_feedback_sr_outcome
            ON recommendation_feedback (service_request_pk, outcome, created_at)
            """
        )

    @staticmethod
    def _build_evidence_packet(
        *,
        request: sqlite3.Row,
        tags: list[dict[str, object]],
        similar: list[sqlite3.Row],
        recommendations: list[dict[str, object]],
    ) -> dict[str, object]:
        tag_values = [str(tag["tag"]) for tag in tags if tag.get("tag")]
        return {
            "tool": "complaint_intelligence.service_request_evidence",
            "version": "evidence.v1",
            "purpose": "Package historical completed-service-request evidence for downstream decision-support clients.",
            "input": {
                "serviceRequestId": request["service_request_id"],
                "complaintText": _truncate(request["complaint_text"], 700),
                "modelNumber": request["model_number"],
                "brand": request["brand"],
                "applianceType": request["appliance_type"],
            },
            "classification": {
                "complaintTags": tag_values,
                "matchedHistoricalRequestCount": len(similar),
            },
            "rankedParts": recommendations,
            "supportingEvidence": [
                {
                    "serviceRequestId": row["service_request_id"],
                    "completedAt": row["completed_at"],
                    "modelNumber": row["model_number"],
                    "brand": row["brand"],
                    "applianceType": row["appliance_type"],
                    "complaintText": _truncate(row["complaint_text"], 700),
                    "resolutionNotes": _truncate(row["resolution_notes"], 500),
                }
                for row in similar[:5]
            ],
            "diagnosticQuestions": _diagnostic_questions(tuple(tag_values)),
            "useConstraints": [
                "Use rankedParts as historical evidence, not a guaranteed diagnosis.",
                "Do not recommend a part that is not present in rankedParts unless clearly labeled as a new hypothesis.",
                "Ask diagnosticQuestions before presenting a parts-first path when evidence is weak or missing.",
                "Prefer model-specific evidence over brand-only or appliance-type-only evidence.",
                "Mention matchedHistoricalRequestCount so the user understands evidence strength.",
            ],
            "confidence": _confidence_label(len(similar), recommendations),
        }

    def _unavailable(self, *, sr_id: int, status: str, message: str) -> dict[str, object]:
        return {
            "success": True,
            "available": False,
            "integrationStatus": status,
            "message": message,
            "srId": str(sr_id),
            "sourcePath": str(Path(self.project_path).expanduser()) if self.project_path else None,
            "request": None,
            "complaintTags": [],
            "billedItems": [],
            "similarRequestCount": 0,
            "recommendations": [],
            "commonResolutions": [],
            "modelFamilyTrends": None,
            "feedbackSummary": {"counts": {}, "latest": None},
            "feedbackCaptureEnabled": False,
            "evidencePacket": None,
        }

    @staticmethod
    def _sqlite_path(database_url: str) -> Path | None:
        if database_url.startswith("sqlite:///"):
            raw = database_url[len("sqlite:///") :]
            if raw.startswith("/"):
                return Path(unquote(raw))
            return Path(unquote(raw)).expanduser()
        if database_url.startswith("sqlite:////"):
            return Path(unquote(database_url[len("sqlite:///") :]))
        return None


def _truncate(value: str | None, max_length: int) -> str | None:
    text_value = (value or "").strip()
    if not text_value:
        return None
    if len(text_value) <= max_length:
        return text_value
    return f"{text_value[:max_length].rstrip()}..."


def _clean_optional(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _normalize_feedback_outcome(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"helpful", "not_helpful", "needs_review"}:
        return normalized
    return None


def _model_family_prefix(model_number: str | None) -> str | None:
    cleaned = "".join(character for character in str(model_number or "").upper() if character.isalnum())
    if not cleaned:
        return None
    return cleaned[:5]


def _confidence_label(similar_request_count: int, recommendations: list[dict[str, object]]) -> str:
    if similar_request_count <= 0 or not recommendations:
        return "no_historical_match"
    top_score = float(recommendations[0].get("score") or 0)
    if similar_request_count >= 10 and top_score >= 0.5:
        return "strong"
    if similar_request_count >= 3 and top_score >= 0.34:
        return "moderate"
    return "limited"


def _diagnostic_questions(tags: tuple[str, ...]) -> list[str]:
    questions_by_tag = {
        "no_cool": [
            "Is the evaporator fan running when the unit is calling for cooling?",
            "Is there frost buildup on the evaporator cover or a blocked return air path?",
            "Are condenser coils, compressor operation, and thermistor readings normal?",
        ],
        "no_heat": [
            "Is the unit receiving the correct voltage at the terminal block?",
            "Does the heating element or igniter test open?",
            "Are thermal cutoffs, thermostats, or airflow restrictions present?",
        ],
        "water_leak": [
            "Where is the leak visible: fill, drain, dispenser, door, or underneath?",
            "Does the leak happen during fill, wash, drain, or idle?",
            "Are hoses, gaskets, dispenser drawer, and drain path seated and clear?",
        ],
        "no_drain": [
            "Does the drain pump run or only hum?",
            "Is the pump filter, drain hose, or standpipe restricted?",
            "Is there voltage at the drain pump during the drain cycle?",
        ],
        "no_spin": [
            "Does the unit drain fully before spin should begin?",
            "Are there balance, lid lock, door lock, or motor control errors?",
            "Does the basket turn freely by hand?",
        ],
        "ice_maker_issue": [
            "Is the ice maker receiving water and reaching harvest temperature?",
            "Are fill tube, inlet valve, water filter, and ice maker error codes checked?",
            "Is the ice room frozen over or leaking air?",
        ],
        "not_igniting": [
            "Is the igniter glowing or sparking during ignition?",
            "Is gas supply present and are burner ports clear?",
            "Do flame sensor, igniter, and safety valve readings match spec?",
        ],
        "error_code": [
            "What exact error code is displayed and when does it appear?",
            "Does the code return after power reset and diagnostic mode?",
            "Which components does the service manual map to that code?",
        ],
        "intermittent_operation": [
            "Can the failure be reproduced, and under what cycle/load/temperature?",
            "Are harness connections, control faults, and stored error codes present?",
            "Does vibration, heat, or moisture appear to trigger the issue?",
        ],
        "noisy": [
            "When does the noise occur: fill, wash, spin, drain, compressor start, or fan operation?",
            "Is the sound mechanical, airflow-related, vibration, scraping, or electrical hum?",
            "Are moving parts, mounts, bearings, fans, and foreign objects checked?",
        ],
    }
    questions: list[str] = []
    for tag in tags:
        questions.extend(questions_by_tag.get(tag, []))
    if not questions:
        questions.extend(
            [
                "What exact symptom does the customer observe?",
                "When does the symptom occur in the cycle or operating state?",
                "Are there model-specific service bulletins or stored error codes?",
            ]
        )
    return list(dict.fromkeys(questions))[:6]
