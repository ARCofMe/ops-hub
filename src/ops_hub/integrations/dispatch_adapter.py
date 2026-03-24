"""Dispatch adapter for incremental wrapper-based migration work."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import logging
import os
from pathlib import Path
import sys
from types import TracebackType
from urllib.parse import quote_plus

from ops_hub.models.requests import BlueFolderJobSummary, DispatchJobSummary


logger = logging.getLogger(__name__)

@dataclass(slots=True)
class DispatchAdapter:
    """Adapter boundary for dispatch-facing operations."""

    base_path: str | None = None
    bluefolder_api_path: str | None = None
    bluefolder_api_key: str | None = None
    bluefolder_account_name: str | None = None
    bluefolder_base_url: str | None = None
    bluefolder_host_header: str | None = None
    bluefolder_verify_ssl: bool | None = None
    bluefolder_timeout_seconds: float | None = None
    _origin_lookup_unavailable: bool = False

    async def get_job(
        self,
        reference: str,
        bluefolder_summary: BlueFolderJobSummary | None = None,
        technician_bluefolder_user_id: int | None = None,
    ) -> DispatchJobSummary:
        """Return dispatch wrapper status and a stop preview when enough data is available."""
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

        module_name = "optimized_routing.routing"
        try:
            with self._dispatch_runtime_context(resolved_path):
                importlib.invalidate_caches()
                sys.modules.pop("optimized_routing", None)
                sys.modules.pop(module_name, None)
                module = importlib.import_module(module_name)
                preview_builder = getattr(module, "bluefolder_to_routestops")
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

        if bluefolder_summary is None or bluefolder_summary.integration_status != "live_read":
            return DispatchJobSummary(
                reference=reference,
                available=True,
                integration_status="wrapper_ready",
                message="Dispatch wrapper is available, but no live BlueFolder job data was available for a stop preview.",
                source_path=resolved_path,
                module_name=module_name,
            )

        if not bluefolder_summary.address:
            return DispatchJobSummary(
                reference=reference,
                available=True,
                integration_status="wrapper_ready",
                message="Dispatch wrapper is available, but the BlueFolder job did not include an address for stop preview.",
                source_path=resolved_path,
                module_name=module_name,
            )

        assignment = {
            "serviceRequestId": bluefolder_summary.service_request_id or reference,
            "address": bluefolder_summary.address,
            "city": bluefolder_summary.city,
            "state": bluefolder_summary.state,
            "zip": bluefolder_summary.postal_code,
            "start": "",
        }
        try:
            with self._dispatch_runtime_context(resolved_path):
                stops = preview_builder([assignment])
        except Exception as exc:
            logger.exception("Failed to build dispatch stop preview for %s", reference)
            return DispatchJobSummary(
                reference=reference,
                available=False,
                integration_status="preview_failed",
                message=f"Dispatch stop preview failed: {exc}",
                source_path=resolved_path,
                module_name=module_name,
            )

        if not stops:
            return DispatchJobSummary(
                reference=reference,
                available=True,
                integration_status="wrapper_ready",
                message="Dispatch wrapper is available, but it did not return any stop previews for this job.",
                source_path=resolved_path,
                module_name=module_name,
            )

        stop = stops[0]
        technician_assignment_status = None
        technician_origin_address = None
        if technician_bluefolder_user_id is not None:
            try:
                with self._dispatch_runtime_context(resolved_path):
                    importlib.invalidate_caches()
                    sys.modules.pop("optimized_routing.bluefolder_integration", None)
                    integration_module = importlib.import_module("optimized_routing.bluefolder_integration")
                    integration_class = getattr(integration_module, "BlueFolderIntegration")
                    integration = integration_class()
                    assignments = integration.get_user_assignments_today(technician_bluefolder_user_id) or []
                    sr_id = str(bluefolder_summary.service_request_id or reference)
                    technician_assignment_status = (
                        "assigned_today"
                        if any(str(a.get("serviceRequestId")) == sr_id for a in assignments)
                        else "not_assigned_today"
                    )
                    technician_origin_address = integration.get_user_origin_address(technician_bluefolder_user_id)
            except Exception as exc:
                logger.warning(
                    "Dispatch technician context unavailable for user %s: %s",
                    technician_bluefolder_user_id,
                    exc,
                )
                technician_assignment_status = f"context_failed: {exc}"

        return DispatchJobSummary(
            reference=reference,
            available=True,
            integration_status="stop_preview",
            message="Dispatch stop preview built from the existing routing wrapper.",
            source_path=resolved_path,
            module_name=module_name,
            stop_label=getattr(stop, "label", None),
            stop_address=getattr(stop, "address", None),
            stop_window=getattr(getattr(stop, "window", None), "name", None),
            technician_assignment_status=technician_assignment_status,
            technician_origin_address=technician_origin_address,
        )

    async def get_assignments_for_user(self, technician_bluefolder_user_id: int) -> list[dict[str, str | bool | None]]:
        """Return today's assignments for a mapped BlueFolder user via the existing routing wrapper."""
        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        if resolved_path is None or not resolved_path.exists():
            return []

        try:
            with self._dispatch_runtime_context(resolved_path):
                importlib.invalidate_caches()
                sys.modules.pop("optimized_routing", None)
                sys.modules.pop("optimized_routing.bluefolder_integration", None)
                integration_module = importlib.import_module("optimized_routing.bluefolder_integration")
                integration_class = getattr(integration_module, "BlueFolderIntegration")
                integration = integration_class()
                assignments = integration.get_user_assignments_today(technician_bluefolder_user_id) or []
        except Exception as exc:
            logger.warning(
                "Dispatch wrapper assignments unavailable for mapped BlueFolder user %s: %s",
                technician_bluefolder_user_id,
                exc,
            )
            return []

        return assignments

    async def get_origin_for_user(self, technician_bluefolder_user_id: int) -> str | None:
        """Return the mapped user's origin address when available from the routing wrapper."""
        if self._origin_lookup_unavailable:
            return None
        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        if resolved_path is None or not resolved_path.exists():
            return None

        try:
            with self._dispatch_runtime_context(resolved_path):
                importlib.invalidate_caches()
                sys.modules.pop("optimized_routing", None)
                sys.modules.pop("optimized_routing.bluefolder_integration", None)
                integration_module = importlib.import_module("optimized_routing.bluefolder_integration")
                integration_class = getattr(integration_module, "BlueFolderIntegration")
                integration = integration_class()
                return integration.get_user_origin_address(technician_bluefolder_user_id)
        except Exception as exc:
            self._origin_lookup_unavailable = True
            logger.warning(
                "Dispatch wrapper origin unavailable for mapped BlueFolder user %s: %s",
                technician_bluefolder_user_id,
                exc,
            )
            return None

    async def build_route_map_urls(
        self,
        stops: list[dict[str, str]],
    ) -> tuple[str | None, str | None]:
        """Build a route link and optional static image URL for a list of stops."""
        if not stops:
            return None, None

        resolved_path = Path(self.base_path).expanduser() if self.base_path else None
        env_values = self._load_dispatch_project_env(resolved_path)
        default_origin = env_values.get("DEFAULT_ORIGIN") or None
        google_maps_api_key = env_values.get("GOOGLE_MAPS_API_KEY") or None

        addresses = [stop["address"] for stop in stops if stop.get("address")]
        if not addresses:
            return None, None

        route_points = [default_origin, *addresses] if default_origin else addresses
        route_url = "https://www.google.com/maps/dir/" + "/".join(
            quote_plus(point) for point in route_points if point
        )

        if not google_maps_api_key:
            return route_url, None

        image_stops = stops[:8]
        params: list[str] = ["size=640x360", "scale=2", "maptype=roadmap"]
        if default_origin:
            params.append(f"markers=color:green%7Clabel:O%7C{quote_plus(default_origin)}")
        for index, stop in enumerate(image_stops, start=1):
            params.append(
                f"markers=color:red%7Clabel:{index}%7C{quote_plus(stop['address'])}"
            )

        path_points = ([default_origin] if default_origin else []) + [stop["address"] for stop in image_stops]
        if len(path_points) >= 2:
            encoded_path = "%7C".join(quote_plus(point) for point in path_points)
            params.append(f"path=color:0x3367d6ff%7Cweight:5%7C{encoded_path}")

        params.append(f"key={quote_plus(google_maps_api_key)}")
        image_url = "https://maps.googleapis.com/maps/api/staticmap?" + "&".join(params)
        return route_url, image_url

    def _load_dispatch_project_env(self, resolved_path: Path | None) -> dict[str, str]:
        """Load selected env values from the dispatch project .env when available."""
        if resolved_path is None:
            return {}
        env_path = resolved_path / ".env"
        if not env_path.exists():
            return {}

        values: dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cleaned = value.strip()
            if " #" in cleaned:
                cleaned = cleaned.split(" #", 1)[0].rstrip()
            values[key.strip()] = cleaned
        return values

    def _dispatch_runtime_context(self, resolved_path: Path) -> "_temporary_dispatch_context":
        """Build the shared runtime context for dispatch wrapper imports and calls."""
        bluefolder_path = (
            Path(self.bluefolder_api_path).expanduser() if self.bluefolder_api_path else None
        )
        return _temporary_dispatch_context(
            dispatch_path=resolved_path,
            bluefolder_path=bluefolder_path,
            api_key=self.bluefolder_api_key,
            account_name=self.bluefolder_account_name,
            base_url=self.bluefolder_base_url,
            host_header=self.bluefolder_host_header,
            verify_ssl=self.bluefolder_verify_ssl,
            timeout_seconds=self.bluefolder_timeout_seconds,
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


class _temporary_dispatch_context:
    """Context manager for dispatch-wrapper imports plus BlueFolder runtime env."""

    def __init__(
        self,
        *,
        dispatch_path: Path,
        bluefolder_path: Path | None,
        api_key: str | None,
        account_name: str | None,
        base_url: str | None,
        host_header: str | None,
        verify_ssl: bool | None,
        timeout_seconds: float | None,
    ) -> None:
        self.dispatch_ctx = _temporary_sys_path(dispatch_path)
        self.bluefolder_ctx = _temporary_sys_path(bluefolder_path) if bluefolder_path else None
        self.values = {
            "BLUEFOLDER_API_KEY": api_key or "",
            "BLUEFOLDER_ACCOUNT_NAME": account_name or "",
            "BLUEFOLDER_BASE_URL": base_url or "",
            "BLUEFOLDER_HOST_HEADER": host_header or "",
            "BLUEFOLDER_VERIFY_SSL": "" if verify_ssl is None else str(verify_ssl).lower(),
            "BLUEFOLDER_TIMEOUT_SECONDS": "" if timeout_seconds is None else str(timeout_seconds),
        }
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        self.dispatch_ctx.__enter__()
        if self.bluefolder_ctx is not None:
            self.bluefolder_ctx.__enter__()
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for key, previous_value in self.previous.items():
            if previous_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous_value
        if self.bluefolder_ctx is not None:
            self.bluefolder_ctx.__exit__(exc_type, exc, tb)
        self.dispatch_ctx.__exit__(exc_type, exc, tb)
