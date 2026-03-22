"""Placeholder adapter for the Parts Cannon subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ops_hub.models.requests import PartsWorkflowSummary

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
