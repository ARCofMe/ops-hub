"""BlueFolder adapter for incremental read-only migration work."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import html
import logging
import os
from pathlib import Path
import re
import sys
from types import TracebackType

from datetime import date, datetime

from ops_hub.models.requests import BlueFolderJobSummary, CustomerContactSummary, PartsCommentRecord


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
    _active_user_directory_cache: dict[int, str] = field(default_factory=dict)
    _active_user_directory_unavailable: bool = False

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
                if isinstance(exc, RuntimeError) and str(exc) == "Invalid XML response":
                    logger.warning("BlueFolder lookup unavailable for %s: %s", reference, exc)
                else:
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
        customer_phone: str | None = self._clean_phone(
            sr.findtext("customerContactPhone")
            or sr.findtext(".//customerContactPhone")
            or sr.findtext("phone")
            or sr.findtext(".//phone")
        )
        customer_contacts: tuple[CustomerContactSummary, ...] = ()
        customer_id = sr.findtext("customerId")
        customer_location_id = sr.findtext("customerLocationId")
        address: str | None = None
        city: str | None = None
        state: str | None = None
        postal_code: str | None = None
        service_request_status = (
            sr.findtext("serviceRequestStatus")
            or sr.findtext("serviceRequestStatusName")
            or sr.findtext("status")
            or sr.findtext("statusName")
            or sr.findtext(".//status")
            or sr.findtext(".//statusName")
        )

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
                contacts: list[dict[str, object]] | None = None
                try:
                    contacts = client.customer_contacts.list_for_customer(int(customer_id))
                except Exception as exc:
                    logger.warning("BlueFolder contact lookup unavailable for customer=%s: %s", customer_id, exc)
                else:
                    customer_contacts = self._build_customer_contacts(contacts or [], customer_location_id)
                    if not customer_phone:
                        customer_phone = self._select_customer_phone(contacts or [], customer_location_id)
                if not customer_phone or not customer_contacts:
                    try:
                        customer_xml = client.customers.get_by_id(int(customer_id))
                    except Exception as exc:
                        logger.warning("BlueFolder customer fallback lookup unavailable for customer=%s: %s", customer_id, exc)
                    else:
                        if not customer_phone:
                            customer_phone = self._clean_phone(
                                customer_xml.findtext(".//customerContactPhone")
                                or customer_xml.findtext(".//phone")
                            )
                        if not customer_contacts:
                            customer_contacts = self._build_customer_contacts_from_customer_xml(customer_xml)

        return BlueFolderJobSummary(
            reference=reference,
            available=True,
            integration_status="live_read",
            message=f"BlueFolder SR `{service_request_id}`: {subject}",
            source_path=resolved_path,
            service_request_id=service_request_id,
            subject=subject,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_id=customer_id,
            customer_location_id=customer_location_id,
            address=address,
            city=city,
            state=state,
            postal_code=postal_code,
            service_request_status=service_request_status,
            customer_contacts=customer_contacts,
        )

    def _select_customer_phone(self, contacts: list[dict[str, object]], customer_location_id: str | None) -> str | None:
        """Choose the best available customer phone for the SR location."""
        preferred = [
            contact
            for contact in contacts
            if str(contact.get("locationId") or "") == str(customer_location_id or "")
        ]
        ordered = preferred + [contact for contact in contacts if contact not in preferred]
        primary = next((contact for contact in ordered if bool(contact.get("isPrimary"))), None)
        if primary is not None and (phone := self._clean_phone(primary.get("phone"))):
            return phone
        for contact in ordered:
            if phone := self._clean_phone(contact.get("phone")):
                return phone
        return None

    def _clean_phone(self, value: object) -> str | None:
        """Normalize a candidate phone value into a printable string."""
        text = str(value or "").strip()
        return text or None

    def _build_customer_contacts(
        self,
        contacts: list[dict[str, object]],
        customer_location_id: str | None,
    ) -> tuple[CustomerContactSummary, ...]:
        """Build ordered customer contact summaries for a location-aware SR."""
        filtered = [
            contact
            for contact in contacts
            if not customer_location_id
            or str(contact.get("locationId") or "") in {"", str(customer_location_id)}
        ]
        if not filtered:
            filtered = contacts

        summaries: list[CustomerContactSummary] = []
        seen: set[tuple[str, str, str, str]] = set()
        for contact in sorted(
            filtered,
            key=lambda item: (
                not bool(item.get("isPrimary")),
                str(item.get("firstName") or "").casefold(),
                str(item.get("lastName") or "").casefold(),
            ),
        ):
            name = " ".join(
                part for part in [str(contact.get("firstName") or "").strip(), str(contact.get("lastName") or "").strip()] if part
            ).strip() or "Unknown"
            summary = CustomerContactSummary(
                name=name,
                title=self._clean_text(contact.get("title")),
                phone=self._clean_phone(contact.get("phone")),
                email=self._clean_text(contact.get("email")),
                is_primary=bool(contact.get("isPrimary")),
            )
            key = (summary.name, summary.title or "", summary.phone or "", summary.email or "")
            if key in seen:
                continue
            seen.add(key)
            summaries.append(summary)
        return tuple(summaries[:5])

    def _build_customer_contacts_from_customer_xml(self, customer_xml) -> tuple[CustomerContactSummary, ...]:
        """Build contact summaries from the broader customer record as a fallback."""
        summaries: list[CustomerContactSummary] = []
        seen: set[tuple[str, str, str, str]] = set()
        for contact in customer_xml.findall(".//customerContact"):
            summary = CustomerContactSummary(
                name=" ".join(
                    part
                    for part in [
                        (contact.findtext("firstName") or "").strip(),
                        (contact.findtext("lastName") or "").strip(),
                    ]
                    if part
                ).strip()
                or "Unknown",
                title=self._clean_text(contact.findtext("title")),
                phone=self._clean_phone(contact.findtext("phone")),
                email=self._clean_text(contact.findtext("email")),
                is_primary=(contact.findtext("isPrimary") == "1"),
            )
            key = (summary.name, summary.title or "", summary.phone or "", summary.email or "")
            if key in seen:
                continue
            seen.add(key)
            summaries.append(summary)
        return tuple(summaries[:5])

    def _clean_text(self, value: object) -> str | None:
        """Normalize a candidate text value into a printable string."""
        text = str(value or "").strip()
        return text or None

    async def get_recent_parts_comments(self, sr_id: int, *, limit: int = 6) -> list[PartsCommentRecord]:
        """Return recent service-request history entries that look parts-related."""
        client, _resolved_path = self._build_client()
        if client is None:
            return []
        try:
            history_xml = client.service_requests.get_history(sr_id)
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc) == "Invalid XML response":
                logger.warning("BlueFolder history lookup unavailable for SR %s: %s", sr_id, exc)
            else:
                logger.exception("BlueFolder history lookup failed for SR %s", sr_id)
            return []

        filtered = [
            PartsCommentRecord(
                author=entry.findtext("userName"),
                date_created=entry.findtext("entryDate"),
                text=self._clean_html_text(
                    entry.findtext("comment") or entry.findtext("description")
                )
                or "",
                is_visible_to_customer=False,
            )
            for entry in history_xml.findall(".//serviceRequestHistory")
            if self._is_parts_comment(
                self._clean_html_text(entry.findtext("comment") or entry.findtext("description")) or ""
            )
        ]
        filtered = [item for item in filtered if item.text]
        filtered.sort(key=lambda item: item.date_created or "", reverse=True)
        return filtered[:limit]

    async def get_assignments_for_user_today(self, user_id: int) -> list[dict[str, str | bool | None]]:
        """Return today's scheduled assignments directly from BlueFolder."""
        client, _resolved_path = self._build_client()
        if client is None:
            return []

        day = date.today()
        start_date = f"{day.strftime('%Y.%m.%d')} 12:00 AM"
        end_date = f"{day.strftime('%Y.%m.%d')} 11:59 PM"
        try:
            assignments = client.assignments.list_for_user_range(
                user_id,
                start_date,
                end_date,
                date_range_type="scheduled",
            )
        except Exception as exc:
            logger.warning("BlueFolder assignment lookup unavailable for user %s: %s", user_id, exc)
            return []

        return self._enrich_assignments(client, assignments or [])

    async def add_parts_comment(
        self,
        sr_id: int,
        *,
        issue_type: str,
        details: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
    ) -> dict[str, str | bool | None]:
        """Add a standardized parts-related comment to a service request."""
        client, _resolved_path = self._build_client()
        if client is None:
            return {"ok": False, "error": "BlueFolder client is not configured for write actions."}

        detail_text = " ".join(details.split()).strip()
        if not detail_text:
            return {"ok": False, "error": "Part details are required."}

        timestamp = datetime.now().replace(second=0, microsecond=0)
        reported_by = self._reported_by_text(requested_by_label, requested_by_user_id)
        if issue_type == "missing_part":
            comment_text = (
                f"Missing part reported at {timestamp.strftime('%I:%M %p').lstrip('0')}. "
                f"Details: {detail_text}. Reported by {reported_by}."
            )
        else:
            comment_text = (
                f"Damaged part reported at {timestamp.strftime('%I:%M %p').lstrip('0')}. "
                f"Details: {detail_text}. Reported by {reported_by}."
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
        requested_by_label: str | None = None,
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
        reported_by = self._reported_by_text(requested_by_label, requested_by_user_id)
        comment_text = (
            f"{prefix} at {timestamp.strftime('%I:%M %p').lstrip('0')}. "
            f"{structured_details} Reported by {reported_by}."
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

    async def add_contact_issue_comment(
        self,
        sr_id: int,
        *,
        issue_type: str,
        details: str | None,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
    ) -> dict[str, str | bool | None]:
        """Add a standardized contact/arrival issue comment to a service request."""
        return await self.add_field_event_comment(
            sr_id,
            event_type=issue_type,
            requested_by_user_id=requested_by_user_id,
            requested_by_label=requested_by_label,
            details=details,
        )

    async def add_route_update_comment(
        self,
        sr_id: int,
        *,
        update_type: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        minutes: int | None = None,
    ) -> dict[str, str | bool | None]:
        """Add a standardized route-status comment to a service request."""
        return await self.add_field_event_comment(
            sr_id,
            event_type=update_type,
            requested_by_user_id=requested_by_user_id,
            requested_by_label=requested_by_label,
            minutes=minutes,
        )

    async def add_field_event_comment(
        self,
        sr_id: int,
        *,
        event_type: str,
        requested_by_user_id: int,
        requested_by_label: str | None = None,
        details: str | None = None,
        minutes: int | None = None,
    ) -> dict[str, str | bool | None]:
        """Add a standardized field-workflow comment to a service request."""
        client, _resolved_path = self._build_client()
        if client is None:
            return {"ok": False, "error": "BlueFolder client is not configured for write actions."}

        timestamp = datetime.now().replace(second=0, microsecond=0)
        comment_text = self._build_field_event_comment_text(
            event_type=event_type,
            timestamp=timestamp,
            requested_by_user_id=requested_by_user_id,
            requested_by_label=requested_by_label,
            details=details,
            minutes=minutes,
        )
        if comment_text is None:
            if event_type == "eta":
                return {"ok": False, "error": "ETA minutes must be greater than 0."}
            if event_type == "enroute":
                return {"ok": False, "error": "ETA minutes must be greater than 0 when provided."}
            if event_type in {"note", "reschedule_needed"}:
                return {"ok": False, "error": "Details are required."}
            return {"ok": False, "error": f"Unsupported field event `{event_type}`."}

        try:
            client.comments.add_to_service_request(
                sr_id,
                comment_text,
                visible_to_customer=False,
            )
        except Exception as exc:
            logger.exception("BlueFolder field-event write failed for SR %s", sr_id)
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "note_text": comment_text,
            "logged_at": timestamp.isoformat(timespec="minutes"),
        }

    def _build_field_event_comment_text(
        self,
        *,
        event_type: str,
        timestamp: datetime,
        requested_by_user_id: int,
        requested_by_label: str | None,
        details: str | None,
        minutes: int | None,
    ) -> str | None:
        """Render a standardized field-workflow comment body."""
        detail_text = " ".join((details or "").split()).strip()
        event_time = timestamp.strftime("%I:%M %p").lstrip("0")
        reported_by = self._reported_by_text(requested_by_label, requested_by_user_id)

        if event_type == "eta":
            if minutes is None or minutes <= 0:
                return None
            body = f"ETA update: arriving in {minutes} minutes."
        elif event_type == "enroute":
            body = f"Technician en route at {event_time}."
            if minutes is not None:
                if minutes <= 0:
                    return None
                body = f"{body} ETA update: arriving in {minutes} minutes."
        elif event_type == "no_answer":
            body = f"Customer no-answer at {event_time}."
            if detail_text:
                body = f"{body} Details: {detail_text}."
        elif event_type == "not_home":
            body = f"Customer not home at arrival at {event_time}."
            if detail_text:
                body = f"{body} Details: {detail_text}."
        elif event_type == "start":
            body = f"Technician started work at {event_time}."
            if detail_text:
                body = f"{body} Details: {detail_text}."
        elif event_type == "note":
            if not detail_text:
                return None
            body = f"Technician field note at {event_time}. Details: {detail_text}."
        elif event_type == "reschedule_needed":
            if not detail_text:
                return None
            body = f"Reschedule needed noted at {event_time}. Reason: {detail_text}."
        else:
            return None

        return f"{body} Reported by {reported_by}."

    def _reported_by_text(self, requested_by_label: str | None, requested_by_user_id: int) -> str:
        """Return a readable actor label for BlueFolder note attribution."""
        text = (requested_by_label or "").strip()
        if text:
            return text
        return f"Discord user {requested_by_user_id}"

    async def get_active_user_directory(self) -> dict[int, str]:
        """Return a BlueFolder active-user directory keyed by user id."""
        if self._active_user_directory_cache:
            return dict(self._active_user_directory_cache)
        if self._active_user_directory_unavailable:
            return {}

        client, _resolved_path = self._build_client()
        if client is None:
            return {}

        try:
            users = client.users.list_active()
        except Exception as exc:
            self._active_user_directory_unavailable = True
            logger.warning("BlueFolder active-user lookup unavailable: %s", exc)
            return {}

        directory: dict[int, str] = {}
        for row in users or []:
            parsed = self._parse_user_row(row)
            if parsed is None:
                continue
            user_id, name = parsed
            directory[user_id] = name

        self._active_user_directory_cache = dict(directory)
        return directory

    async def get_user_name(self, user_id: int) -> str | None:
        """Return a readable BlueFolder user name when available."""
        directory = await self.get_active_user_directory()
        if user_id in directory:
            return directory[user_id]
        if self._active_user_directory_unavailable:
            return None

        client, _resolved_path = self._build_client()
        if client is None:
            return None

        try:
            row = client.users.get_by_id(user_id)
        except Exception as exc:
            logger.warning("BlueFolder user lookup unavailable for user %s: %s", user_id, exc)
            return None

        parsed = self._parse_user_row(row)
        if parsed is None:
            return None
        parsed_user_id, name = parsed
        self._active_user_directory_cache[parsed_user_id] = name
        return name

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

    def _parse_user_row(self, row: object) -> tuple[int, str] | None:
        """Extract a stable id/name pair from a BlueFolder user row."""
        if not isinstance(row, dict):
            return None
        raw_id = row.get("id") or row.get("userId")
        try:
            user_id = int(str(raw_id))
        except (TypeError, ValueError):
            return None
        first_name = str(row.get("firstName") or "").strip()
        last_name = str(row.get("lastName") or "").strip()
        name = " ".join(part for part in [first_name, last_name] if part).strip() or f"Tech {user_id}"
        return user_id, name

    def _enrich_assignments(
        self,
        client: object,
        assignments: list[dict[str, object]],
    ) -> list[dict[str, str | bool | None]]:
        """Normalize raw BlueFolder assignment rows for Discord-facing command output."""
        results: list[dict[str, str | bool | None]] = []
        for row in assignments:
            if not isinstance(row, dict):
                continue
            service_request_id = row.get("serviceRequestId")
            subject = None
            sr_lookup_id = self._safe_int(service_request_id)
            if sr_lookup_id is not None:
                try:
                    sr_xml = client.service_requests.get_by_id(sr_lookup_id)
                    sr = sr_xml.find(".//serviceRequest")
                    if sr is not None:
                        subject = sr.findtext("description") or sr.findtext("subject")
                except Exception as exc:
                    if isinstance(exc, RuntimeError) and str(exc) == "Invalid XML response":
                        logger.warning(
                            "BlueFolder assignment subject lookup unavailable for SR %s: %s",
                            sr_lookup_id,
                            exc,
                        )
                    else:
                        logger.warning(
                            "BlueFolder assignment subject lookup failed for SR %s: %s",
                            sr_lookup_id,
                            exc,
                        )
                    subject = None

            results.append(
                {
                    "assignmentId": self._stringify(row.get("assignmentId")),
                    "serviceRequestId": self._stringify(service_request_id),
                    "subject": subject or "Service Request",
                    "start": self._stringify(row.get("start")),
                    "end": self._stringify(row.get("end")),
                    "routeLabel": self._stringify(
                        row.get("routeLabel") or row.get("window") or row.get("timeWindow")
                    ),
                    "city": self._stringify(row.get("city")),
                    "state": self._stringify(row.get("state")),
                    "isComplete": row.get("isComplete") if isinstance(row.get("isComplete"), bool) else None,
                }
            )

        return sorted(results, key=lambda item: item.get("start") or "")

    def _clean_html_text(self, value: str | None) -> str | None:
        """Normalize simple BlueFolder HTML/text content for Discord display."""
        if value is None:
            return None

        text = str(value)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</li\s*>", "\n", text)
        text = re.sub(r"(?i)<li\s*>", "- ", text)
        text = re.sub(r"(?i)</p\s*>", "\n\n", text)
        text = re.sub(r"(?i)<p\s*>", "", text)
        text = re.sub(r"(?i)</?ul\s*>", "", text)
        text = re.sub(r"(?i)</?ol\s*>", "", text)
        text = re.sub(r"(?i)</?label\s*>", "", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.strip() for line in text.splitlines())
        text = text.strip()
        return text or None

    @staticmethod
    def _safe_int(value: object) -> int | None:
        """Best-effort integer parsing."""
        try:
            return int(value)  # type: ignore[arg-type]
        except Exception:
            return None

    @staticmethod
    def _stringify(value: object) -> str | None:
        """Return a stripped string value or ``None``."""
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

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
