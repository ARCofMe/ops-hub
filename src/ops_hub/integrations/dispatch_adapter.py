"""Placeholder adapter for dispatch and job lookup integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DispatchAdapter:
    """Adapter boundary for dispatch-facing operations."""

    base_path: str | None = None

    async def get_job(self, reference: str) -> dict[str, str]:
        """Return a placeholder dispatch lookup response.

        TODO: Wrap existing dispatch/job lookup logic from current projects here.
        """
        return {
            "reference": reference,
            "status": "placeholder",
            "source": "dispatch_adapter",
        }

