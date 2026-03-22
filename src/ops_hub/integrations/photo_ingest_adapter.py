"""Placeholder adapter for photo ingest and compliance integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PhotoIngestAdapter:
    """Adapter boundary for photo ingest behavior."""

    base_path: str | None = None

    async def healthcheck(self) -> dict[str, str]:
        """Return a placeholder photo-ingest health response.

        TODO: Plug in existing photo ingest and compliance projects here.
        """
        return {"status": "placeholder", "source": "photo_ingest_adapter"}

