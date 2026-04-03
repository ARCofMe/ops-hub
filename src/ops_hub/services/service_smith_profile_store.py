"""File-backed store for intake profiles."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ops_hub.services.file_store_utils import atomic_write_text


@dataclass(slots=True)
class IntakeProfileRecord:
    """Persisted import profile for spreadsheet intake."""

    name: str
    format_name: str = "default"
    field_map_path: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    limit: int | None = 25
    duplicate_mode: str = "skip"
    preview_mode: str = "plan"
    fail_fast: bool = False
    updated_by_user_id: int | None = None


@dataclass(slots=True)
class ServiceSmithProfileStore:
    """Load and persist saved intake profiles."""

    file_path: Path | None = None
    records: list[IntakeProfileRecord] = field(default_factory=list)

    def load(self) -> list[IntakeProfileRecord]:
        """Load profiles from disk if configured."""
        if self.file_path is None or not self.file_path.exists():
            return list(self.records)

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise RuntimeError(f"ServiceSmith profile file must contain a JSON array: {self.file_path}")
        self.records = [IntakeProfileRecord(**item) for item in raw]
        return list(self.records)

    def save(self, records: list[IntakeProfileRecord]) -> Path | None:
        """Persist profiles to disk if configured."""
        self.records = list(records)
        if self.file_path is None:
            return None

        atomic_write_text(
            self.file_path,
            json.dumps([asdict(record) for record in self.records], indent=2),
        )
        return self.file_path
