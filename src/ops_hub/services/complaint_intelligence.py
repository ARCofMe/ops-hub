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
