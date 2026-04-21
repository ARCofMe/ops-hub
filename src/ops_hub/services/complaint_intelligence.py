"""Read-only Complaint Intelligence integration for Ops Hub."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from urllib.parse import unquote


@dataclass(slots=True)
class ComplaintIntelligenceService:
    """Query normalized complaint intelligence data for RouteDesk decision support."""

    database_url: str | None = None
    project_path: str | None = None

    async def get_service_request_payload(
        self,
        *,
        sr_id: int,
        current_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
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
                    live_payload = self._build_live_context_payload(conn, sr_id=sr_id, current_context=current_context)
                    if live_payload is not None:
                        return live_payload
                    return self._unavailable(
                        sr_id=sr_id,
                        status="not_found",
                        message=f"No Complaint Intelligence record is available for SR {sr_id}.",
                    )
                tags = self._fetch_tags(conn, request["id"])
                billed_items = self._fetch_billed_items(conn, request["id"])
                match_scope, similar = self._fetch_similar_requests(conn, request, tags)
                recommendations = self._fetch_recommendations(conn, similar, request=request, tags=tags)
                common_resolutions = self._fetch_common_resolutions(conn, similar)
                model_family_trends = self._fetch_model_family_trends(conn, request)
                feedback_summary = self._fetch_feedback_summary(conn, request["id"])
                feedback_health = _feedback_health(feedback_summary)
                evidence_packet = self._build_evidence_packet(
                    request=request,
                    tags=tags,
                    similar=similar,
                    recommendations=recommendations,
                    match_scope=match_scope,
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
            "feedbackHealth": feedback_health,
            "feedbackCaptureEnabled": True,
            "evidencePacket": evidence_packet,
        }

    def _build_live_context_payload(
        self,
        conn: sqlite3.Connection,
        *,
        sr_id: int,
        current_context: dict[str, object] | None,
    ) -> dict[str, object] | None:
        """Build historical evidence from live BlueFolder context for an SR not yet ingested."""
        if not isinstance(current_context, dict):
            return None
        complaint_text = _clean_optional(current_context.get("complaintText"), max_length=2000)
        if complaint_text is None:
            return None

        request = {
            "id": None,
            "service_request_id": str(sr_id),
            "completed_at": None,
            "model_number": _clean_optional(current_context.get("modelNumber"), max_length=128),
            "brand": _clean_optional(current_context.get("brand"), max_length=128),
            "appliance_type": _clean_optional(current_context.get("applianceType"), max_length=128),
            "complaint_text": complaint_text,
            "resolution_notes": None,
        }
        tags = [
            {"tag": tag, "confidence": 1.0, "source": "rules_live_context"}
            for tag in _classify_complaint_text(complaint_text)
        ]
        match_scope, similar = self._fetch_similar_requests(conn, request, tags)
        recommendations = self._fetch_recommendations(conn, similar, request=request, tags=tags)
        common_resolutions = self._fetch_common_resolutions(conn, similar)
        model_family_trends = self._fetch_model_family_trends(conn, request)
        evidence_packet = self._build_evidence_packet(
            request=request,
            tags=tags,
            similar=similar,
            recommendations=recommendations,
            match_scope=match_scope,
        )
        return {
            "success": True,
            "available": True,
            "integrationStatus": "live_context",
            "message": "Built Complaint Intelligence evidence from live BlueFolder context because this SR has not been ingested yet.",
            "srId": str(sr_id),
            "sourcePath": str(Path(self.project_path).expanduser()) if self.project_path else None,
            "request": {
                "serviceRequestId": str(sr_id),
                "completedAt": None,
                "modelNumber": request["model_number"],
                "brand": request["brand"],
                "applianceType": request["appliance_type"],
                "complaintText": request["complaint_text"],
                "resolutionNotes": None,
            },
            "complaintTags": tags,
            "billedItems": [],
            "similarRequestCount": len(similar),
            "recommendations": recommendations,
            "commonResolutions": common_resolutions,
            "modelFamilyTrends": model_family_trends,
            "feedbackSummary": {"counts": {}, "latest": None},
            "feedbackHealth": _feedback_health({"counts": {}, "latest": None}),
            "feedbackCaptureEnabled": False,
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
                        service_request_pk, outcome, actor_user_id, source, recommended_item, notes, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        int(request["id"]),
                        normalized_outcome,
                        actor_user_id,
                        _clean_optional(source, max_length=64) or "unknown",
                        _clean_optional(recommended_item, max_length=128),
                        _clean_optional(notes, max_length=1000),
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

    async def seed_historical_feedback(self, *, limit: int = 250) -> dict[str, object]:
        """Populate initial positive feedback from completed SR billed parts."""
        if not (db_path := self._ready_sqlite_path()):
            return {"success": False, "message": "Complaint Intelligence database is not configured.", "inserted": 0}
        inserted = 0
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_feedback_table(conn)
                rows = conn.execute(
                    """
                    SELECT sr.id AS service_request_pk, COALESCE(NULLIF(bi.sku, ''), bi.description) AS recommended_item
                    FROM service_requests sr
                    JOIN billed_items bi ON bi.service_request_pk = sr.id
                    WHERE bi.item_type != 'labor'
                      AND COALESCE(NULLIF(bi.sku, ''), bi.description) IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM recommendation_feedback rf
                          WHERE rf.service_request_pk = sr.id
                            AND rf.source = 'historical_completion'
                            AND rf.recommended_item = COALESCE(NULLIF(bi.sku, ''), bi.description)
                      )
                    ORDER BY sr.completed_at DESC
                    LIMIT ?
                    """,
                    (max(1, min(int(limit), 1000)),),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        """
                        INSERT INTO recommendation_feedback (
                            service_request_pk, outcome, actor_user_id, source, recommended_item, notes, created_at
                        )
                        VALUES (?, 'helpful', NULL, 'historical_completion', ?, 'Seeded from completed SR billed item.', CURRENT_TIMESTAMP)
                        """,
                        (row["service_request_pk"], row["recommended_item"]),
                    )
                    inserted += 1
                conn.commit()
        except sqlite3.Error as exc:
            return {"success": False, "message": f"Complaint Intelligence feedback seed failed: {exc}", "inserted": inserted}
        return {"success": True, "message": f"Seeded {inserted} historical feedback records.", "inserted": inserted}

    async def resolve_feedback_review(
        self,
        *,
        feedback_id: int,
        decision: str,
        actor_user_id: int | None,
        notes: str | None = None,
    ) -> dict[str, object]:
        """Resolve weak evidence feedback and persist its model/complaint/part decision."""
        normalized_decision = _normalize_review_decision(decision)
        if normalized_decision is None:
            raise ValueError("Review decision must be one of `trusted`, `downgraded`, or `excluded`.")
        if not (db_path := self._ready_sqlite_path()):
            raise ValueError("Complaint Intelligence review requires a local SQLite database.")
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_feedback_table(conn)
                row = conn.execute(
                    """
                    SELECT rf.id, rf.recommended_item, sr.model_number, ct.tag AS complaint_tag
                    FROM recommendation_feedback rf
                    JOIN service_requests sr ON sr.id = rf.service_request_pk
                    LEFT JOIN complaint_tags ct ON ct.service_request_pk = sr.id
                    WHERE rf.id = ?
                    ORDER BY ct.tag ASC
                    LIMIT 1
                    """,
                    (feedback_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Feedback `{feedback_id}` was not found.")
                review_notes = _clean_optional(notes, max_length=1000)
                conn.execute(
                    """
                    UPDATE recommendation_feedback
                    SET review_status = 'resolved',
                        review_decision = ?,
                        reviewed_by_user_id = ?,
                        reviewed_at = CURRENT_TIMESTAMP,
                        review_notes = ?
                    WHERE id = ?
                    """,
                    (normalized_decision, actor_user_id, review_notes, feedback_id),
                )
                recommended_item = _clean_optional(row["recommended_item"], max_length=128)
                if recommended_item:
                    conn.execute(
                        """
                        INSERT INTO recommendation_part_overrides (
                            model_number, complaint_tag, recommended_item, decision, notes, actor_user_id, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            _clean_optional(row["model_number"], max_length=128),
                            _clean_optional(row["complaint_tag"], max_length=64),
                            recommended_item,
                            normalized_decision,
                            review_notes,
                            actor_user_id,
                        ),
                    )
                conn.commit()
        except sqlite3.Error as exc:
            raise ValueError(f"Complaint Intelligence review write failed: {exc}") from exc
        return {
            "success": True,
            "feedbackId": feedback_id,
            "decision": normalized_decision,
            "message": f"Resolved feedback {feedback_id} as {normalized_decision}.",
        }

    async def get_feedback_review_queue(self, *, limit: int = 25) -> dict[str, object]:
        """Return evidence feedback that needs operator review."""
        if not (db_path := self._ready_sqlite_path()):
            return {"success": True, "available": False, "items": [], "message": "Complaint Intelligence database is not configured."}
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_feedback_table(conn)
                rows = conn.execute(
                    """
                    SELECT
                        rf.id,
                        rf.outcome,
                        rf.source,
                        rf.recommended_item,
                        rf.notes,
                        rf.actor_user_id,
                        rf.created_at,
                        sr.service_request_id,
                        sr.model_number,
                        sr.brand,
                        sr.appliance_type,
                        sr.complaint_text
                    FROM recommendation_feedback rf
                    JOIN service_requests sr ON sr.id = rf.service_request_pk
                    WHERE rf.outcome IN ('needs_review', 'not_helpful')
                      AND COALESCE(rf.review_status, 'open') != 'resolved'
                    ORDER BY rf.created_at DESC, rf.id DESC
                    LIMIT ?
                    """,
                    (max(1, min(int(limit), 100)),),
                ).fetchall()
        except sqlite3.Error as exc:
            return {"success": True, "available": False, "items": [], "message": f"Complaint Intelligence review queue failed: {exc}"}
        return {
            "success": True,
            "available": True,
            "items": [
                {
                    "feedbackId": row["id"],
                    "serviceRequestId": row["service_request_id"],
                    "outcome": row["outcome"],
                    "source": row["source"],
                    "recommendedItem": row["recommended_item"],
                    "notes": row["notes"],
                    "actorUserId": row["actor_user_id"],
                    "createdAt": row["created_at"],
                    "modelNumber": row["model_number"],
                    "brand": row["brand"],
                    "applianceType": row["appliance_type"],
                    "complaintText": _truncate(row["complaint_text"], 500),
                }
                for row in rows
            ],
        }

    async def get_dashboard_payload(self) -> dict[str, object]:
        """Return aggregate Complaint Intelligence adoption and feedback health metrics."""
        if not (db_path := self._ready_sqlite_path()):
            return {"success": True, "available": False, "message": "Complaint Intelligence database is not configured."}
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_feedback_table(conn)
                totals = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_feedback,
                        SUM(CASE WHEN outcome = 'helpful' THEN 1 ELSE 0 END) AS helpful,
                        SUM(CASE WHEN outcome = 'needs_review' THEN 1 ELSE 0 END) AS needs_review,
                        SUM(CASE WHEN outcome = 'not_helpful' THEN 1 ELSE 0 END) AS not_helpful
                    FROM recommendation_feedback
                    """
                ).fetchone()
                weak_rows = conn.execute(
                    """
                    SELECT
                        COALESCE(recommended_item, 'unspecified') AS recommended_item,
                        COUNT(*) AS weak_count,
                        MAX(created_at) AS latest_feedback_at
                    FROM recommendation_feedback
                    WHERE outcome IN ('needs_review', 'not_helpful')
                    GROUP BY COALESCE(recommended_item, 'unspecified')
                    ORDER BY weak_count DESC, latest_feedback_at DESC
                    LIMIT 5
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            return {"success": True, "available": False, "message": f"Complaint Intelligence dashboard failed: {exc}"}

        helpful = int(totals["helpful"] or 0)
        needs_review = int(totals["needs_review"] or 0)
        not_helpful = int(totals["not_helpful"] or 0)
        total = int(totals["total_feedback"] or 0)
        return {
            "success": True,
            "available": True,
            "feedbackVolume": total,
            "helpfulCount": helpful,
            "needsReviewCount": needs_review,
            "notHelpfulCount": not_helpful,
            "helpfulRate": round(helpful / total, 3) if total else None,
            "reviewQueueCount": needs_review + not_helpful,
            "weakRecommendations": [
                {
                    "recommendedItem": row["recommended_item"],
                    "weakFeedbackCount": row["weak_count"],
                    "latestFeedbackAt": row["latest_feedback_at"],
                }
                for row in weak_rows
            ],
        }

    def _ready_sqlite_path(self) -> Path | None:
        db_path = self._sqlite_path(self.database_url or "")
        if db_path is None or not db_path.exists():
            return None
        return db_path

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
        request: sqlite3.Row | dict[str, object],
        tags: list[dict[str, object]],
    ) -> tuple[str, list[sqlite3.Row]]:
        tag_values = [str(tag["tag"]) for tag in tags if tag.get("tag")]
        if not tag_values:
            return "no_classification", []
        placeholders = ",".join("?" for _ in tag_values)
        for match_scope, filters in _match_scope_candidates(
            model_number=request["model_number"],
            brand=request["brand"],
            appliance_type=request["appliance_type"],
        ):
            rows = conn.execute(
                f"""
                SELECT DISTINCT sr.id, sr.service_request_id, sr.completed_at, sr.model_number, sr.brand, sr.appliance_type,
                       sr.complaint_text, sr.resolution_notes
                FROM service_requests sr
                JOIN complaint_tags ct ON ct.service_request_pk = sr.id
                WHERE ct.tag IN ({placeholders})
                  AND (? IS NULL OR sr.model_number = ?)
                  AND (? IS NULL OR REPLACE(REPLACE(REPLACE(UPPER(sr.model_number), '-', ''), '/', ''), '.', '') LIKE ?)
                  AND (? IS NULL OR sr.brand = ?)
                  AND (? IS NULL OR sr.appliance_type = ?)
                ORDER BY sr.completed_at DESC
                LIMIT 25
                """,
                tag_values
                + [
                    filters["model_number"],
                    filters["model_number"],
                    filters["model_prefix"],
                    filters["model_prefix"],
                    filters["brand"],
                    filters["brand"],
                    filters["appliance_type"],
                    filters["appliance_type"],
                ],
            ).fetchall()
            if rows:
                return match_scope, rows
        return "complaint_only", []

    @staticmethod
    def _fetch_recommendations(
        conn: sqlite3.Connection,
        similar: list[sqlite3.Row],
        *,
        request: sqlite3.Row | dict[str, object],
        tags: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        if not similar:
            return []
        ids = [row["id"] for row in similar]
        placeholders = ",".join("?" for _ in ids)
        feedback_by_item = ComplaintIntelligenceService._fetch_feedback_by_item(conn)
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
        decisions = ComplaintIntelligenceService._fetch_part_decisions(conn, request=request, tags=tags)
        recommendations = []
        for row in rows:
            item_name = str(row["item"])
            decision = decisions.get(item_name)
            if decision == "excluded":
                continue
            feedback = feedback_by_item.get(item_name, {"helpful": 0, "needs_review": 0, "not_helpful": 0})
            base_score = float(row["matching_request_count"]) / denominator
            decision_adjustment = 0.15 if decision == "trusted" else -0.15 if decision == "downgraded" else 0.0
            score = max(
                0.0,
                min(
                    1.0,
                    base_score
                    + decision_adjustment
                    + (0.05 * int(feedback.get("helpful") or 0))
                    - (0.03 * int(feedback.get("needs_review") or 0))
                    - (0.1 * int(feedback.get("not_helpful") or 0)),
                ),
            )
            recommendations.append(
                {
                    "item": row["item"],
                    "itemType": row["item_type"],
                    "seenCount": row["seen_count"],
                    "matchingRequestCount": row["matching_request_count"],
                    "baseScore": round(base_score, 4),
                    "score": round(score, 4),
                    "feedbackWeight": {
                        "helpful": int(feedback.get("helpful") or 0),
                        "needsReview": int(feedback.get("needs_review") or 0),
                        "notHelpful": int(feedback.get("not_helpful") or 0),
                    },
                    "reviewDecision": decision,
                }
            )
        return sorted(recommendations, key=lambda item: (-float(item["score"]), str(item["item"])))[:10]

    @staticmethod
    def _fetch_part_decisions(
        conn: sqlite3.Connection,
        *,
        request: sqlite3.Row | dict[str, object],
        tags: list[dict[str, object]],
    ) -> dict[str, str]:
        ComplaintIntelligenceService._ensure_feedback_table(conn)
        tag_values = [str(tag["tag"]) for tag in tags if tag.get("tag")]
        if not tag_values:
            tag_values = [""]
        placeholders = ",".join("?" for _ in tag_values)
        rows = conn.execute(
            f"""
            SELECT recommended_item, decision
            FROM recommendation_part_overrides
            WHERE (model_number IS NULL OR model_number = ?)
              AND (complaint_tag IS NULL OR complaint_tag IN ({placeholders}))
            ORDER BY created_at DESC, id DESC
            """,
            [_clean_optional(request["model_number"], max_length=128), *tag_values],
        ).fetchall()
        decisions: dict[str, str] = {}
        for row in rows:
            item = str(row["recommended_item"])
            if item not in decisions:
                decisions[item] = str(row["decision"])
        return decisions

    @staticmethod
    def _fetch_feedback_by_item(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
        ComplaintIntelligenceService._ensure_feedback_table(conn)
        rows = conn.execute(
            """
            SELECT recommended_item, outcome, COUNT(*) AS feedback_count
            FROM recommendation_feedback
            WHERE recommended_item IS NOT NULL AND recommended_item != ''
            GROUP BY recommended_item, outcome
            """
        ).fetchall()
        feedback: dict[str, dict[str, int]] = {}
        for row in rows:
            item = str(row["recommended_item"])
            feedback.setdefault(item, {})[str(row["outcome"])] = int(row["feedback_count"])
        return feedback

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
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(recommendation_feedback)").fetchall()
        }
        column_sql = {
            "review_status": "ALTER TABLE recommendation_feedback ADD COLUMN review_status VARCHAR(32) DEFAULT 'open'",
            "review_decision": "ALTER TABLE recommendation_feedback ADD COLUMN review_decision VARCHAR(32)",
            "reviewed_by_user_id": "ALTER TABLE recommendation_feedback ADD COLUMN reviewed_by_user_id INTEGER",
            "reviewed_at": "ALTER TABLE recommendation_feedback ADD COLUMN reviewed_at DATETIME",
            "review_notes": "ALTER TABLE recommendation_feedback ADD COLUMN review_notes TEXT",
        }
        for column, sql in column_sql.items():
            if column not in existing_columns:
                conn.execute(sql)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_part_overrides (
                id INTEGER PRIMARY KEY,
                model_number VARCHAR(128),
                complaint_tag VARCHAR(64),
                recommended_item VARCHAR(128) NOT NULL,
                decision VARCHAR(32) NOT NULL,
                notes TEXT,
                actor_user_id INTEGER,
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
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_feedback_review_status
            ON recommendation_feedback (review_status, outcome, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_part_overrides_pattern
            ON recommendation_part_overrides (model_number, complaint_tag, recommended_item, created_at)
            """
        )

    @staticmethod
    def _build_evidence_packet(
        *,
        request: sqlite3.Row,
        tags: list[dict[str, object]],
        similar: list[sqlite3.Row],
        recommendations: list[dict[str, object]],
        match_scope: str,
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
                "matchScope": match_scope,
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
            "feedbackHealth": _feedback_health({"counts": {}, "latest": None}),
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


def _clean_optional(value: object | None, *, max_length: int | None = None) -> str | None:
    cleaned = str(value or "").strip()
    if max_length is not None and len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned or None


def _normalize_feedback_outcome(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"helpful", "not_helpful", "needs_review"}:
        return normalized
    return None


def _normalize_review_decision(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"trusted", "downgraded", "excluded"}:
        return normalized
    return None


def _feedback_health(feedback_summary: dict[str, object]) -> dict[str, object]:
    counts = feedback_summary.get("counts") if isinstance(feedback_summary, dict) else {}
    if not isinstance(counts, dict):
        counts = {}
    helpful = int(counts.get("helpful") or 0)
    needs_review = int(counts.get("needs_review") or 0)
    not_helpful = int(counts.get("not_helpful") or 0)
    total = helpful + needs_review + not_helpful
    if total == 0:
        status = "no_feedback"
        label = "No operator feedback yet"
    elif not_helpful > helpful:
        status = "caution"
        label = "Prior feedback says this evidence has been weak"
    elif needs_review >= helpful and needs_review > 0:
        status = "needs_review"
        label = "Prior feedback needs review before relying on this evidence"
    elif helpful > 0 and not_helpful == 0:
        status = "supportive"
        label = "Prior feedback supports this evidence"
    else:
        status = "mixed"
        label = "Prior feedback is mixed"
    helpful_rate = round(helpful / total, 3) if total else None
    return {
        "status": status,
        "label": label,
        "totalFeedback": total,
        "helpfulRate": helpful_rate,
    }


def _model_family_prefix(model_number: str | None) -> str | None:
    cleaned = "".join(character for character in str(model_number or "").upper() if character.isalnum())
    if not cleaned:
        return None
    return cleaned[:5]


def _match_scope_candidates(
    *,
    model_number: object | None,
    brand: object | None,
    appliance_type: object | None,
) -> tuple[tuple[str, dict[str, str | None]], ...]:
    model = _clean_optional(model_number)
    brand_value = _clean_optional(brand)
    appliance = _clean_optional(appliance_type)
    candidates: list[tuple[str, dict[str, str | None]]] = []
    if model:
        candidates.append(
            (
                "exact_model",
                {"model_number": model, "model_prefix": None, "brand": brand_value, "appliance_type": appliance},
            )
        )
        model_prefix = _model_family_prefix(model)
        if model_prefix:
            candidates.append(
                (
                    "model_family",
                    {"model_number": None, "model_prefix": f"{model_prefix}%", "brand": brand_value, "appliance_type": appliance},
                )
            )
    if brand_value and appliance:
        candidates.append(
            (
                "brand_appliance_type",
                {"model_number": None, "model_prefix": None, "brand": brand_value, "appliance_type": appliance},
            )
        )
    if appliance:
        candidates.append(
            (
                "appliance_type",
                {"model_number": None, "model_prefix": None, "brand": None, "appliance_type": appliance},
            )
        )
    candidates.append(
        (
            "complaint_only",
            {"model_number": None, "model_prefix": None, "brand": None, "appliance_type": None},
        )
    )
    return tuple(candidates)


TAG_PATTERNS: dict[str, tuple[str, ...]] = {
    "no_cool": (r"\bno cool\b", r"\bnot cool", r"\bwarm\b", r"\bnot cooling\b"),
    "no_heat": (r"\bno heat\b", r"\bnot heat", r"\bnot heating\b", r"\bdoesn.?t heat\b", r"\bwill not preheat\b"),
    "water_leak": (r"\bleak", r"\bwater.*floor\b", r"\bdripping\b"),
    "noisy": (r"\bnoise\b", r"\bnoisy\b", r"\bgrind", r"\brattle", r"\bsqueal", r"\bbanging\b"),
    "no_spin": (r"\bno spin\b", r"\bnot spinning\b", r"\bwon.?t spin\b"),
    "no_drain": (r"\bno drain\b", r"\bnot drain", r"\bnot draining\b", r"\bwon.?t drain\b", r"\bpump running\b"),
    "ice_maker_issue": (r"\bice maker\b", r"\bno ice\b", r"\bnot making ice\b", r"\bice bucket\b"),
    "not_igniting": (r"\bnot ignit", r"\bwon.?t light\b", r"\bno flame\b"),
    "error_code": (r"\berror code\b", r"\bfault code\b", r"\bcode [a-z0-9-]+\b", r"\b[a-z]{1,3}\d{1,3}\b"),
    "intermittent_operation": (r"\bintermittent\b", r"\bsometimes\b", r"\boff and on\b", r"\bstops mid"),
    "no_power": (r"\bno power\b", r"\bwon.?t power on\b", r"\bwill not power on\b", r"\bwon.?t turn on\b"),
    "display_issue": (r"\bdisplay\b", r"\bscreen\b", r"\bno picture\b", r"\bback ?light\b"),
    "not_drying": (r"\bnot drying\b", r"\bdoes not dry\b", r"\bclothes.*wet\b"),
    "fill_issue": (r"\bno water\b", r"\bnot fill", r"\bdoes not fill\b", r"\bfill error\b"),
    "not_cleaning": (r"\bnot clean", r"\bdishes.*dirty\b", r"\bpoor wash\b"),
}


def _classify_complaint_text(complaint_text: str | None) -> tuple[str, ...]:
    haystack = str(complaint_text or "").casefold()
    if not haystack:
        return ()
    return tuple(
        tag
        for tag, patterns in TAG_PATTERNS.items()
        if any(re.search(pattern, haystack) for pattern in patterns)
    )


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
