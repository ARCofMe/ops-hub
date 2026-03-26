"""File-backed parts request store."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ops_hub.models.requests import PartRequestRecord
from ops_hub.services.file_store_utils import atomic_write_text


@dataclass(slots=True)
class PartsRequestStore:
    """Load and persist lightweight parts requests."""

    file_path: Path | None = None
    records: list[PartRequestRecord] = field(default_factory=list)

    def load(self) -> list[PartRequestRecord]:
        """Load parts requests from disk if configured and present."""
        if self.file_path is None or not self.file_path.exists():
            return list(self.records)

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise RuntimeError(f"Parts request file must contain a JSON array: {self.file_path}")
        self.records = [PartRequestRecord(**item) for item in raw]
        return list(self.records)

    def save(self, records: list[PartRequestRecord]) -> Path | None:
        """Persist parts requests to disk if configured."""
        self.records = list(records)
        if self.file_path is None:
            return None

        atomic_write_text(
            self.file_path,
            json.dumps([asdict(record) for record in self.records], indent=2),
        )
        return self.file_path
