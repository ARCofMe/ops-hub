"""Placeholder adapter for the Parts Cannon subsystem."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PartsCannonAdapter:
    """Adapter boundary for parts workflow integration."""

    base_path: str | None = None

    async def get_part_status(self, reference: str) -> dict[str, str]:
        """Return a placeholder parts lookup result.

        TODO: Wrap existing parts-related projects and workflows gradually.
        """
        return {
            "reference": reference,
            "status": "placeholder",
            "source": "parts_cannon_adapter",
        }

