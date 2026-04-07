"""Parts handoff adapter for optional downstream queue export/import."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ops_hub.models.requests import (
    PartRequestRecord,
    PartsExportSummary,
    PartsImportSummary,
    PartsReceiptRecord,
    PartsWorkflowSummary,
)
from ops_hub.services.file_store_utils import atomic_write_text

@dataclass(slots=True)
class PartsHandoffAdapter:
    """Adapter boundary for optional parts handoff integration."""

    base_path: str | None = None

    async def get_part_status(self, reference: str) -> PartsWorkflowSummary:
        """Return current parts handoff integration status."""
        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        if resolved_path is None:
            return PartsWorkflowSummary(
                reference=reference,
                available=False,
                integration_status="unconfigured",
                message="Parts workflow path is not configured yet.",
                source_path=None,
            )

        if not resolved_path.exists():
            return PartsWorkflowSummary(
                reference=reference,
                available=False,
                integration_status="missing_path",
                message="Parts workflow path is configured but does not exist.",
                source_path=resolved_path,
            )

        export_path = resolved_path / "ops_hub_exports" / "parts_requests.json"
        receipt_path = resolved_path / "ops_hub_exports" / "parts_request_receipts.json"
        return PartsWorkflowSummary(
            reference=reference,
            available=True,
            integration_status="handoff_ready",
            message="Parts handoff directory is available for request export and receipt import.",
            source_path=resolved_path,
            export_path=export_path,
            export_file_exists=export_path.exists(),
            receipt_path=receipt_path,
            receipt_file_exists=receipt_path.exists(),
        )

    async def export_requests(self, records: list[PartRequestRecord]) -> PartsExportSummary:
        """Export tracked parts requests to a downstream handoff file under the configured path."""
        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        if resolved_path is None:
            return PartsExportSummary(
                available=False,
                integration_status="unconfigured",
                message="Parts workflow path is not configured yet.",
                exported_count=0,
                export_path=None,
            )

        if not resolved_path.exists():
            return PartsExportSummary(
                available=False,
                integration_status="missing_path",
                message="Parts workflow path is configured but does not exist.",
                exported_count=0,
                export_path=resolved_path,
            )

        export_path = resolved_path / "ops_hub_exports" / "parts_requests.json"
        atomic_write_text(
            export_path,
            json.dumps([asdict(record) for record in records], indent=2),
        )
        return PartsExportSummary(
            available=True,
            integration_status="exported",
            message="Tracked parts requests were exported to the downstream handoff file.",
            exported_count=len(records),
            export_path=export_path,
        )

    async def import_receipts(self) -> PartsImportSummary:
        """Import downstream receipt updates from the configured parts workflow path."""
        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        if resolved_path is None:
            return PartsImportSummary(
                available=False,
                integration_status="unconfigured",
                message="Parts workflow path is not configured yet.",
                imported_count=0,
                receipt_path=None,
                receipts=[],
            )

        if not resolved_path.exists():
            return PartsImportSummary(
                available=False,
                integration_status="missing_path",
                message="Parts workflow path is configured but does not exist.",
                imported_count=0,
                receipt_path=resolved_path,
                receipts=[],
            )

        receipt_path = resolved_path / "ops_hub_exports" / "parts_request_receipts.json"
        if not receipt_path.exists():
            return PartsImportSummary(
                available=True,
                integration_status="no_receipts",
                message="No downstream parts receipt file was found yet.",
                imported_count=0,
                receipt_path=receipt_path,
                receipts=[],
            )

        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError(f"Parts receipt file must contain a JSON array: {receipt_path}")
        receipts = [PartsReceiptRecord(**item) for item in payload]
        return PartsImportSummary(
            available=True,
            integration_status="imported",
            message="Downstream parts receipts were loaded from the handoff directory.",
            imported_count=len(receipts),
            receipt_path=receipt_path,
            receipts=receipts,
        )


PartsCannonAdapter = PartsHandoffAdapter
