"""File-backed technician mapping store."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ops_hub.models.requests import TechnicianMappingRecord
from ops_hub.services.file_store_utils import atomic_write_text


@dataclass(slots=True)
class OperatorMappingStore:
    """Load and persist technician-to-BlueFolder user mappings."""

    file_path: Path | None = None
    records: dict[int, int] = field(default_factory=dict)

    def load(self) -> dict[int, int]:
        """Load mappings from disk if configured and present."""
        if self.file_path is None or not self.file_path.exists():
            return dict(self.records)

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"Technician mapping file must contain a JSON object: {self.file_path}")
        self.records = {int(k): int(v) for k, v in raw.items()}
        return dict(self.records)

    def export(self, records: dict[int, int]) -> Path | None:
        """Persist mappings to the configured file path."""
        self.records = dict(records)
        if self.file_path is None:
            return None

        atomic_write_text(
            self.file_path,
            json.dumps({str(k): v for k, v in sorted(records.items())}, indent=2),
        )
        return self.file_path

    def current_records(self) -> list[TechnicianMappingRecord]:
        """Return typed records sorted by Discord user id."""
        return [
            TechnicianMappingRecord(discord_user_id=discord_user_id, bluefolder_user_id=bluefolder_user_id)
            for discord_user_id, bluefolder_user_id in sorted(self.records.items())
        ]
