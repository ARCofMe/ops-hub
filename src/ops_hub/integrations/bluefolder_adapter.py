"""BlueFolder adapter for incremental read-only migration work."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import logging
import os
from pathlib import Path
import re
import sys
from types import TracebackType

from datetime import datetime

from ops_hub.models.requests import BlueFolderJobSummary, PartsCommentRecord


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BlueFolderAdapter:
    """Adapter boundary for BlueFolder-facing behavior."""

    base_path: str | None = None
    api_key: str | None = None
    account_name: str | None = None
    base_url: str | None = None
    host_header: str | None = None
    verify_ssl: bool | None = None
    timeout_seconds: float | None = None
    parts_comment_keywords: tuple[str, ...] = (
        "part",
        "tracking",
        "eta",
        "ship",
        "ordered",
        "order",
        "backorder",
        "received",
    )

    async def get_job_summary(self, reference: str) -> BlueFolderJobSummary:
        """Return a read-only BlueFolder lookup result when the local library is available."""
        resolved_path = self._resolve_path()
        if resolved_path is None:
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="unconfigured",
                message="BlueFolder adapter path is not configured yet.",
                source_path=None,
            )

        if not resolved_path.exists():
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="missing_path",
                message="BlueFolder adapter path is configured but does not exist.",
                source_path=resolved_path,
            )

        service_request_id = self._extract_service_request_id(reference)
        if service_request_id is None:
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="unsupported_reference",
                message="BlueFolder read-only lookup currently requires a numeric SR id.",
                source_path=resolved_path,
            )

        try:
            client_class = self._load_client_class(resolved_path)
        except (ImportError, AttributeError, ModuleNotFoundError) as exc:
            logger.exception("Failed to load bluefolder_api from %s", resolved_path)
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="import_error",
                message=f"Failed to import bluefolder_api from configured path: {exc}",
                source_path=resolved_path,
                service_request_id=service_request_id,
            )

        if not (self.api_key or "").strip():
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="client_unconfigured",
                message="BlueFolder API key is not configured for Ops Hub.",
                source_path=resolved_path,
                service_request_id=service_request_id,
            )

        if not ((self.account_name or "").strip() or (self.base_url or "").strip()):
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="client_unconfigured",
                message="BlueFolder account name or base URL is not configured for Ops Hub.",
                source_path=resolved_path,
                service_request_id=service_request_id,
            )

        with _temporary_sys_path(resolved_path), _temporary_bluefolder_env(
            api_key=self.api_key,
            account_name=self.account_name,
            base_url=self.base_url,
            host_header=self.host_header,
            verify_ssl=self.verify_ssl,
            timeout_seconds=self.timeout_seconds,
        ):
            try:
                client = client_class(base_url=(self.base_url or None))
                sr_xml = client.service_requests.get_by_id(int(service_request_id))
            except Exception as exc:
                logger.exception("BlueFolder lookup failed for %s", reference)
                return BlueFolderJobSummary(
                    reference=reference,
                    available=False,
                    integration_status="lookup_failed",
                    message=f"BlueFolder read-only lookup failed: {exc}",
                    source_path=resolved_path,
                    service_request_id=service_request_id,
                )

        sr = sr_xml.find(".//serviceRequest")
        if sr is None:
            return BlueFolderJobSummary(
                reference=reference,
                available=False,
                integration_status="not_found",
                message=f"No BlueFolder service request was found for `{service_request_id}`.",
                source_path=resolved_path,
                service_request_id=service_request_id,
            )

        subject = (
            sr.findtext("description")
            or sr.findtext("subject")
            or sr.findtext(".//subject")
            or sr.findtext(".//title")
            or "Unlabeled Service Request"
        )
        customer_name = sr.findtext("customerName") or sr.findtext(".//customerName")
        customer_id = sr.findtext("customerId")
        customer_location_id = sr.findtext("customerLocationId")
        address: str | None = None
        city: str | None = None
        state: str | None = None
        postal_code: str | None = None

        if customer_id and customer_location_id:
            with _temporary_sys_path(resolved_path), _temporary_bluefolder_env(
                api_key=self.api_key,
                account_name=self.account_name,
                base_url=self.base_url,
                host_header=self.host_header,
                verify_ssl=self.verify_ssl,
                timeout_seconds=self.timeout_seconds,
            ):
                try:
                    client = client_class(base_url=(self.base_url or None))
                    loc_xml = client.customers.get_location_by_id(customer_id, customer_location_id)
                except Exception:
                    logger.exception(
                        "BlueFolder location lookup failed for customer=%s location=%s",
                        customer_id,
                        customer_location_id,
                    )
                else:
                    location = loc_xml.find(".//customerLocation")
                    if location is not None:
                        address = location.findtext("addressStreet")
                        city = location.findtext("addressCity")
                        state = location.findtext("addressState")
                        postal_code = location.findtext("addressPostalCode")

        return BlueFolderJobSummary(
            reference=reference,
            available=True,
            integration_status="live_read",
            message=f"BlueFolder SR `{service_request_id}`: {subject}",
            source_path=resolved_path,
            service_request_id=service_request_id,
            subject=subject,
            customer_name=customer_name,
            customer_id=customer_id,
            customer_location_id=customer_location_id,
            address=address,
            city=city,
            state=state,
            postal_code=postal_code,
        )

    async def get_recent_parts_comments(self, sr_id: int, *, limit: int = 6) -> list[PartsCommentRecord]:
        """Return recent service-request comments that look parts-related."""
        client, _resolved_path = self._build_client()
        if client is None:
            return []
        try:
            comments = client.comments.list_for_service_request(sr_id)
        except Exception:
            logger.exception("BlueFolder comment lookup failed for SR %s", sr_id)
            return []

        filtered = [
            PartsCommentRecord(
                author=comment.get("author"),
                date_created=comment.get("dateCreated"),
                text=str(comment.get("text") or ""),
                is_visible_to_customer=bool(comment.get("isVisibleToCustomer")),
            )
            for comment in comments
            if self._is_parts_comment(str(comment.get("text") or ""))
        ]
        filtered.sort(key=lambda item: item.date_created or "", reverse=True)
        return filtered[:limit]

    async def add_parts_comment(
        self,
        sr_id: int,
        *,
        issue_type: str,
        details: str,
        requested_by_user_id: int,
    ) -> dict[str, str | bool | None]:
        """Add a standardized parts-related comment to a service request."""
        client, _resolved_path = self._build_client()
        if client is None:
            return {"ok": False, "error": "BlueFolder client is not configured for write actions."}

        detail_text = " ".join(details.split()).strip()
        if not detail_text:
            return {"ok": False, "error": "Part details are required."}

        timestamp = datetime.now().replace(second=0, microsecond=0)
        if issue_type == "missing_part":
            comment_text = (
                f"Missing part reported at {timestamp.strftime('%I:%M %p').lstrip('0')}. "
                f"Details: {detail_text}. Reported by Discord user {requested_by_user_id}."
            )
        else:
            comment_text = (
                f"Damaged part reported at {timestamp.strftime('%I:%M %p').lstrip('0')}. "
                f"Details: {detail_text}. Reported by Discord user {requested_by_user_id}."
            )

        try:
            client.comments.add_to_service_request(
                sr_id,
                comment_text,
                visible_to_customer=False,
            )
        except Exception as exc:
            logger.exception("BlueFolder comment write failed for SR %s", sr_id)
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "note_text": comment_text,
            "logged_at": timestamp.isoformat(timespec="minutes"),
        }

    async def add_parts_update_comment(
        self,
        sr_id: int,
        *,
        update_type: str,
        details: str,
        requested_by_user_id: int,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, str | bool | None]:
        """Add a standardized parts-status update comment to a service request."""
        client, _resolved_path = self._build_client()
        if client is None:
            return {"ok": False, "error": "BlueFolder client is not configured for write actions."}

        detail_text = " ".join(details.split()).strip()
        if not detail_text:
            return {"ok": False, "error": "Update details are required."}

        timestamp = datetime.now().replace(second=0, microsecond=0)
        prefixes = {
            "part_ordered": "Part ordered",
            "part_eta": "Part ETA update",
            "part_tracking": "Part tracking update",
            "part_received": "Part received",
            "part_ready": "Part ready for scheduling",
        }
        prefix = prefixes.get(update_type, "Parts update")
        structured_details = self._build_parts_update_detail_text(update_type, detail_text, metadata or {})
        comment_text = (
            f"{prefix} at {timestamp.strftime('%I:%M %p').lstrip('0')}. "
            f"{structured_details} Reported by Discord user {requested_by_user_id}."
        )

        try:
            client.comments.add_to_service_request(
                sr_id,
                comment_text,
                visible_to_customer=False,
            )
        except Exception as exc:
            logger.exception("BlueFolder update write failed for SR %s", sr_id)
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "note_text": comment_text,
            "logged_at": timestamp.isoformat(timespec="minutes"),
        }

    def _build_parts_update_detail_text(
        self,
        update_type: str,
        detail_text: str,
        metadata: dict[str, str],
    ) -> str:
        """Render a more structured details block for standardized parts updates."""
        fields: list[str] = []
        if update_type == "part_ordered":
            if vendor := metadata.get("vendor"):
                fields.append(f"Vendor: {vendor}.")
            if eta := metadata.get("eta"):
                fields.append(f"ETA: {eta}.")
        elif update_type == "part_eta":
            if eta := metadata.get("eta"):
                fields.append(f"ETA: {eta}.")
            if carrier := metadata.get("carrier"):
                fields.append(f"Carrier: {carrier}.")
        elif update_type == "part_tracking":
            if carrier := metadata.get("carrier"):
                fields.append(f"Carrier: {carrier}.")
            if tracking_number := metadata.get("tracking_number"):
                fields.append(f"Tracking #: {tracking_number}.")
            if eta := metadata.get("eta"):
                fields.append(f"ETA: {eta}.")
        elif update_type == "part_received":
            if received_from := metadata.get("received_from"):
                fields.append(f"Received from: {received_from}.")
        elif update_type == "part_ready":
            if ready_note := metadata.get("ready_note"):
                fields.append(f"Scheduling note: {ready_note}.")

        fields.append(f"Details: {detail_text}.")
        return " ".join(fields)

    def _extract_service_request_id(self, reference: str) -> str | None:
        """Extract a numeric SR id from a user-supplied lookup token."""
        match = re.search(r"(\d+)", reference)
        return match.group(1) if match else None

    def _resolve_path(self) -> Path | None:
        """Resolve the configured BlueFolder library path."""
        return Path(self.base_path).expanduser() if self.base_path else None

    def _build_client(self) -> tuple[object | None, Path | None]:
        """Construct a BlueFolder client when the local repo path and credentials are usable."""
        resolved_path = self._resolve_path()
        if resolved_path is None or not resolved_path.exists():
            return None, resolved_path
        try:
            client_class = self._load_client_class(resolved_path)
        except (ImportError, AttributeError, ModuleNotFoundError):
            logger.exception("Failed to load bluefolder_api from %s", resolved_path)
            return None, resolved_path
        if not (self.api_key or "").strip():
            return None, resolved_path
        if not ((self.account_name or "").strip() or (self.base_url or "").strip()):
            return None, resolved_path

        with _temporary_sys_path(resolved_path), _temporary_bluefolder_env(
            api_key=self.api_key,
            account_name=self.account_name,
            base_url=self.base_url,
            host_header=self.host_header,
            verify_ssl=self.verify_ssl,
            timeout_seconds=self.timeout_seconds,
        ):
            client = client_class(base_url=(self.base_url or None))
        return client, resolved_path

    def _is_parts_comment(self, text: str) -> bool:
        """Return whether a comment looks relevant to the parts workflow."""
        candidate = text.casefold()
        return any(keyword in candidate for keyword in self.parts_comment_keywords)

    def _load_client_class(self, resolved_path: Path) -> type[object]:
        """Load the shared BlueFolder client from a local repo path."""
        with _temporary_sys_path(resolved_path):
            importlib.invalidate_caches()
            sys.modules.pop("bluefolder_api", None)
            sys.modules.pop("bluefolder_api.client", None)
            module = importlib.import_module("bluefolder_api.client")
        return getattr(module, "BlueFolderClient")


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


class _temporary_bluefolder_env:
    """Context manager for configuring the shared BlueFolder client safely."""

    def __init__(
        self,
        api_key: str | None,
        account_name: str | None,
        base_url: str | None,
        host_header: str | None,
        verify_ssl: bool | None,
        timeout_seconds: float | None,
    ) -> None:
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
