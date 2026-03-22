"""Placeholder BlueFolder adapter for future migration work."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BlueFolderAdapter:
    """Adapter boundary for BlueFolder-facing behavior."""

    base_path: str | None = None

    async def get_job_summary(self, reference: str) -> dict[str, str]:
        """Return a placeholder BlueFolder lookup result.

        TODO: Wrap existing local BlueFolder libraries instead of implementing new logic here first.
        """
        return {
            "reference": reference,
            "status": "placeholder",
            "source": "bluefolder_adapter",
        }

