"""Placeholder adapter for the Parts Cannon subsystem."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from dataclasses import dataclass
from pathlib import Path

from ops_hub.models.requests import PartRequestRecord, PartsExportSummary, PartsWorkflowSummary

@dataclass(slots=True)
class PartsCannonAdapter:
    """Adapter boundary for parts workflow integration."""

    base_path: str | None = None

    async def get_part_status(self, reference: str) -> PartsWorkflowSummary:
        """Return a placeholder parts lookup result.

        TODO: Wrap existing parts-related projects and workflows gradually.
        """
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

        return PartsWorkflowSummary(
            reference=reference,
            available=True,
            integration_status="placeholder_ready",
            message="Parts workflow wrapper path is available. Wrapper behavior is not implemented yet.",
            source_path=resolved_path,
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
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            json.dumps([asdict(record) for record in records], indent=2),
            encoding="utf-8",
        )
        return PartsExportSummary(
            available=True,
            integration_status="exported",
            message="Tracked parts requests were exported to the downstream handoff file.",
            exported_count=len(records),
            export_path=export_path,
        )
