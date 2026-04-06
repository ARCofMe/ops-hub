"""File-backed store for Ops Hub workflow state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ops_hub.models.requests import (
    AttentionItemRecord,
    PartsCaseRecord,
    PhotoComplianceRecord,
    WorkflowEventRecord,
    WorkflowStateSnapshot,
)
from ops_hub.services.file_store_utils import atomic_write_text


@dataclass(slots=True)
class WorkflowStateStore:
    """Load and persist Ops Hub-owned workflow state."""

    file_path: Path | None = None
    snapshot: WorkflowStateSnapshot | None = None

    def load(self) -> WorkflowStateSnapshot:
        """Load workflow state from disk if configured and present."""
        if self.file_path is None or not self.file_path.exists():
            if self.snapshot is None:
                self.snapshot = WorkflowStateSnapshot()
            return self.snapshot

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"Workflow state file must contain a JSON object: {self.file_path}")

        self.snapshot = WorkflowStateSnapshot(
            updated_at=raw.get("updated_at"),
            attention_items=[AttentionItemRecord(**item) for item in raw.get("attention_items", [])],
            photo_compliance_records=[
                PhotoComplianceRecord(**item) for item in raw.get("photo_compliance_records", [])
            ],
            parts_cases=[PartsCaseRecord(**item) for item in raw.get("parts_cases", [])],
            events=[WorkflowEventRecord(**item) for item in raw.get("events", [])],
        )
        return self.snapshot

    def save(self, snapshot: WorkflowStateSnapshot) -> Path | None:
        """Persist workflow state to disk if configured."""
        self.snapshot = snapshot
        if self.file_path is None:
            return None

        atomic_write_text(self.file_path, json.dumps(asdict(snapshot), indent=2))
        return self.file_path
