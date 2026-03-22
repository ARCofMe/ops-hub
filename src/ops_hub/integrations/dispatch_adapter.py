"""Dispatch adapter for incremental wrapper-based migration work."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import logging
from pathlib import Path
import sys
from types import TracebackType

from ops_hub.models.requests import DispatchJobSummary


logger = logging.getLogger(__name__)

@dataclass(slots=True)
class DispatchAdapter:
    """Adapter boundary for dispatch-facing operations."""

    base_path: str | None = None

    async def get_job(self, reference: str) -> DispatchJobSummary:
        """Return dispatch wrapper status for a future job lookup integration."""
        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        if resolved_path is None:
            return DispatchJobSummary(
                reference=reference,
                available=False,
                integration_status="unconfigured",
                message="Dispatch project path is not configured yet.",
                source_path=None,
            )

        if not resolved_path.exists():
            return DispatchJobSummary(
                reference=reference,
                available=False,
                integration_status="missing_path",
                message="Dispatch project path is configured but does not exist.",
                source_path=resolved_path,
            )

        module_name = "optimized_routing.bluefolder_integration"
        try:
            with _temporary_sys_path(resolved_path):
                module = importlib.import_module(module_name)
                integration_class = getattr(module, "BlueFolderIntegration")
        except (ImportError, AttributeError, ModuleNotFoundError) as exc:
            logger.exception("Failed to load dispatch wrapper from %s", resolved_path)
            return DispatchJobSummary(
                reference=reference,
                available=False,
                integration_status="import_error",
                message=f"Failed to import dispatch wrapper from configured path: {exc}",
                source_path=resolved_path,
                module_name=module_name,
            )

        return DispatchJobSummary(
            reference=reference,
            available=True,
            integration_status="wrapper_ready",
            message=(
                f"Dispatch wrapper `{integration_class.__name__}` is importable. "
                "Route and assignment lookup behavior is not wired into Ops Hub yet."
            ),
            source_path=resolved_path,
            module_name=module_name,
        )


class _temporary_sys_path:
    """Context manager that temporarily prepends a path to ``sys.path``."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def __enter__(self) -> None:
        if self.path not in sys.path:
            sys.path.insert(0, self.path)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            sys.path.remove(self.path)
        except ValueError:
            pass
