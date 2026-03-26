"""File-backed store for photo workflow feature overrides."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ops_hub.services.file_store_utils import atomic_write_text


@dataclass(slots=True)
class PhotoFeatureStore:
    """Load and persist photo feature overrides."""

    file_path: Path | None = None
    records: dict[str, bool] = field(default_factory=dict)

    def load(self) -> dict[str, bool]:
        """Load overrides from disk if configured and present."""
        if self.file_path is None or not self.file_path.exists():
            return dict(self.records)

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"Photo feature override file must contain a JSON object: {self.file_path}")
        self.records = {str(key): bool(value) for key, value in raw.items()}
        return dict(self.records)

    def export(self, records: dict[str, bool]) -> Path | None:
        """Persist overrides to the configured file path."""
        self.records = dict(records)
        if self.file_path is None:
            return None

        atomic_write_text(
            self.file_path,
            json.dumps({key: value for key, value in sorted(records.items())}, indent=2),
        )
        return self.file_path
