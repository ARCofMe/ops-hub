"""Placeholder BlueFolder adapter for future migration work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ops_hub.models.requests import BlueFolderJobSummary

@dataclass(slots=True)
class BlueFolderAdapter:
    """Adapter boundary for BlueFolder-facing behavior."""

    base_path: str | None = None

    async def get_job_summary(self, reference: str) -> BlueFolderJobSummary:
        """Return a placeholder BlueFolder lookup result.

        TODO: Wrap existing local BlueFolder libraries instead of implementing new logic here first.
        """
        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        if resolved_path is None:
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="unconfigured",
                message="BlueFolder adapter path is not configured yet.",
                source_path=None,
            )

        if not resolved_path.exists():
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="missing_path",
                message="BlueFolder adapter path is configured but does not exist.",
                source_path=resolved_path,
            )

        return BlueFolderJobSummary(
            reference=reference,
            available=True,
            integration_status="placeholder_ready",
            message="BlueFolder adapter path is available. Read-only wrapper not implemented yet.",
            source_path=resolved_path,
        )
