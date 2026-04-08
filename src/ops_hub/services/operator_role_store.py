"""File-backed BlueFolder operator role override store."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ops_hub.services.file_store_utils import atomic_write_text


@dataclass(slots=True)
class OperatorRoleStore:
    """Persist BlueFolder user role overrides keyed by BlueFolder user id."""

    file_path: Path | None = None
    records: dict[int, str] = field(default_factory=dict)

    def load(self) -> dict[int, str]:
        """Load overrides from disk if configured and present."""
        if self.file_path is None or not self.file_path.exists():
            return dict(self.records)

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"Operator role file must contain a JSON object: {self.file_path}")
        self.records = {
            int(str(k)): str(v).strip()
            for k, v in raw.items()
            if str(k).strip().isdigit() and str(v).strip()
        }
        return dict(self.records)

    def export(self, records: dict[int, str]) -> Path | None:
        """Persist overrides to the configured file path."""
        self.records = {int(k): str(v).strip() for k, v in records.items() if str(v).strip()}
        if self.file_path is None:
            return None
        atomic_write_text(
            self.file_path,
            json.dumps({str(k): v for k, v in sorted(self.records.items())}, indent=2),
        )
        return self.file_path
