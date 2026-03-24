"""Runtime feature gates for photo workflows."""

from __future__ import annotations

from dataclasses import dataclass, field

from ops_hub.services.photo_feature_store import PhotoFeatureStore


PHOTO_FEATURE_LABELS: dict[str, str] = {
    "mdlsn_upload": "BlueFolder SR photo upload",
    "photo_archive_handoff": "Archive email handoff",
    "photo_mailbox_scan": "Mailbox scan",
    "weekly_missing_photo_notices": "Weekly missing-photo notices",
}


@dataclass(slots=True)
class PhotoFeatureFlagsService:
    """Combine env defaults with persisted admin overrides."""

    defaults: dict[str, bool]
    store: PhotoFeatureStore
    overrides: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Load persisted overrides after construction."""
        self.overrides = self.store.load()

    def is_enabled(self, feature: str) -> bool:
        """Return the effective value for a known feature."""
        self._require_known_feature(feature)
        if feature in self.overrides:
            return self.overrides[feature]
        return self.defaults[feature]

    def set_override(self, feature: str, enabled: bool) -> None:
        """Persist an explicit runtime override."""
        self._require_known_feature(feature)
        self.overrides[feature] = enabled
        self.store.export(self.overrides)

    def clear_override(self, feature: str) -> bool:
        """Remove a persisted runtime override."""
        self._require_known_feature(feature)
        removed = feature in self.overrides
        if removed:
            self.overrides.pop(feature, None)
            self.store.export(self.overrides)
        return removed

    def status_lines(self) -> list[str]:
        """Return human-readable feature status lines."""
        lines: list[str] = []
        for feature, label in PHOTO_FEATURE_LABELS.items():
            enabled = self.is_enabled(feature)
            source = "override" if feature in self.overrides else "env"
            lines.append(f"`{feature}`: `{'enabled' if enabled else 'disabled'}` via `{source}` ({label})")
        return lines

    def _require_known_feature(self, feature: str) -> None:
        """Reject unknown feature names."""
        if feature not in PHOTO_FEATURE_LABELS:
            raise ValueError(f"Unknown photo feature `{feature}`.")
