"""BlueFolder-backed import planning helpers migrated from ServiceSmith."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import os
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from ops_hub.core.config import Settings
from ops_hub.integrations.import_context import TemporarySysPath, import_module_from_path


@dataclass(slots=True)
class BlueFolderImportResult:
    row_number: str | None
    customer_id: str | None
    customer_location_id: str | None
    customer_contact_id: str | None
    service_request_id: str | None
    existing_service_request_id: str | None = None
    created_customer: bool = False
    created_location: bool = False
    created_contact: bool = False
    status: str = "imported"
    notes: list[str] | None = None


@dataclass(slots=True)
class BlueFolderImportPlan:
    row_number: str | None
    customer_action: str
    location_action: str
    contact_action: str
    service_request_action: str
    existing_customer_id: str | None = None
    existing_location_id: str | None = None
    existing_contact_id: str | None = None
    existing_service_request_id: str | None = None
    notes: list[str] | None = None


@dataclass(slots=True)
class BlueFolderPayloadPreview:
    row_number: str | None
    customer_payload: dict[str, Any] | None
    location_payload: dict[str, Any] | None
    contact_payload: dict[str, Any] | None
    service_request_payload: dict[str, Any] | None
    existing_customer_id: str | None = None
    existing_location_id: str | None = None
    existing_contact_id: str | None = None
    existing_service_request_id: str | None = None
    notes: list[str] | None = None


class ServiceSmithBlueFolderClient:
    """Thin adapter over the shared bluefolder-api package."""

    def __init__(self, settings: Settings) -> None:
        resolved_path = Path(settings.bluefolder_api_path).expanduser() if settings.bluefolder_api_path else None
        if resolved_path is None or not resolved_path.exists():
            raise RuntimeError("OPS_HUB_BLUEFOLDER_API_PATH must point at the BlueFolder client repo for intake preview/import.")
        if not (settings.bluefolder_api_key or "").strip():
            raise RuntimeError("OPS_HUB_BLUEFOLDER_API_KEY is required for intake preview/import.")
        if not ((settings.bluefolder_account_name or "").strip() or (settings.bluefolder_base_url or "").strip()):
            raise RuntimeError("BlueFolder account or base URL is required for intake preview/import.")

        self.settings = settings
        self.client = self._build_client(resolved_path)
        self._customer_cache: list[dict[str, str]] | None = None
        self._service_request_cache: dict[str, str] | None = None

    def preview_payloads(self, row: dict[str, Any], duplicate_mode: str = "skip") -> BlueFolderPayloadPreview:
        customer = self.find_customer(row)
        customer_id = str(customer.get("id") or customer.get("customerId")) if customer else None
        location = self.find_location(customer_id, row) if customer_id else None
        contact = self.find_contact(customer_id, row) if customer_id else None
        existing_service_request_id = self.find_service_request_by_external_id(row.get("external_id"))

        notes: list[str] = []
        if customer:
            notes.append("customer already exists")
        if location:
            notes.append("location already exists")
        if contact:
            notes.append("contact already exists")
        if existing_service_request_id:
            notes.append("service request already exists")
            if duplicate_mode == "allow":
                notes.append("duplicate mode allows create despite existing service request")
            elif duplicate_mode == "error":
                notes.append("duplicate mode would block import")

        customer_payload = None if customer else self.build_customer_payload(row)
        location_payload = None if location or (not customer_id and not row.get("customer_name")) else self.build_location_payload(row)
        contact_payload = None if contact else self.build_contact_payload(row, location_id=str(location.get("id")) if location else None)
        service_request_payload = self.build_service_request_payload(
            row,
            customer_id=customer_id or "<new_customer_id>",
            customer_location_id=str(location.get("id")) if location else "<new_location_id>",
            customer_contact_id=str(contact.get("id")) if contact else "<new_contact_id>",
        )
        return BlueFolderPayloadPreview(
            row_number=row.get("source_row_number"),
            customer_payload=customer_payload,
            location_payload=location_payload,
            contact_payload=contact_payload,
            service_request_payload=service_request_payload,
            existing_customer_id=customer_id,
            existing_location_id=str(location.get("id")) if location else None,
            existing_contact_id=str(contact.get("id")) if contact else None,
            existing_service_request_id=existing_service_request_id,
            notes=notes,
        )

    def plan_import(self, row: dict[str, Any], duplicate_mode: str = "skip") -> BlueFolderImportPlan:
        customer = self.find_customer(row)
        customer_id = str(customer.get("id") or customer.get("customerId")) if customer else None
        location = self.find_location(customer_id, row) if customer_id else None
        contact = self.find_contact(customer_id, row) if customer_id else None
        existing_service_request_id = self.find_service_request_by_external_id(row.get("external_id"))
        notes: list[str] = []
        if existing_service_request_id:
            notes.append("service request already exists in BlueFolder")
        if customer:
            notes.append("customer already exists in BlueFolder")
        elif row.get("customer_name"):
            notes.append("customer would be created")
        else:
            notes.append("service request would be created without a matched customer")
        if location:
            notes.append("location already exists for customer")
        elif row.get("address"):
            notes.append("location would be created")
        if contact:
            notes.append("contact already exists for customer")
        elif row.get("customer_email") or row.get("customer_phone") or row.get("contact_first_name") or row.get("contact_last_name"):
            notes.append("contact would be created")
        if row.get("external_id"):
            notes.append(f"external_id={row['external_id']}")
        if existing_service_request_id and duplicate_mode == "allow":
            notes.append("duplicate mode allows create despite existing service request")
        return BlueFolderImportPlan(
            row_number=row.get("source_row_number"),
            customer_action="use_existing" if customer else "create_customer",
            location_action="use_existing" if location else "create_location",
            contact_action="use_existing" if contact else "create_contact",
            service_request_action=(
                "create_service_request"
                if not existing_service_request_id or duplicate_mode == "allow"
                else "error_duplicate" if duplicate_mode == "error"
                else "skip_existing"
            ),
            existing_customer_id=customer_id,
            existing_location_id=str(location.get("id")) if location else None,
            existing_contact_id=str(contact.get("id")) if contact else None,
            existing_service_request_id=existing_service_request_id,
            notes=notes,
        )

    def ensure_customer_and_import(self, row: dict[str, Any], duplicate_mode: str = "skip") -> BlueFolderImportResult:
        notes: list[str] = []
        existing_service_request_id = self.find_service_request_by_external_id(row.get("external_id"))
        if existing_service_request_id:
            notes.append("service request already exists in BlueFolder")
            if duplicate_mode == "allow":
                notes.append("duplicate mode allows creating another service request")
            elif duplicate_mode == "error":
                return BlueFolderImportResult(
                    row_number=row.get("source_row_number"),
                    customer_id=None,
                    customer_location_id=None,
                    customer_contact_id=None,
                    service_request_id=None,
                    existing_service_request_id=existing_service_request_id,
                    status="duplicate_conflict",
                    notes=notes,
                )
            else:
                return BlueFolderImportResult(
                    row_number=row.get("source_row_number"),
                    customer_id=None,
                    customer_location_id=None,
                    customer_contact_id=None,
                    service_request_id=None,
                    existing_service_request_id=existing_service_request_id,
                    status="skipped_duplicate",
                    notes=notes,
                )

        customer = self.find_customer(row)
        created_customer = False
        created_location = False
        created_contact = False
        customer_id = None
        if customer:
            customer_id = str(customer.get("customerId") or customer.get("id") or "")
            notes.append("matched existing customer")
        elif row.get("customer_name"):
            customer_id = self.create_customer(row)
            created_customer = bool(customer_id)
            if created_customer:
                notes.append("created customer")
                self._customer_cache = None

        existing_location = self.find_location(customer_id, row) if customer_id else None
        location_id = self.ensure_location(customer_id, row) if customer_id else None
        if location_id and row.get("address"):
            created_location = bool(location_id and not existing_location)
            notes.append("created location" if created_location else "matched existing location")

        existing_contact = self.find_contact(customer_id, row) if customer_id else None
        contact_id = self.ensure_contact(customer_id, location_id, row) if customer_id else None
        if contact_id and (row.get("customer_email") or row.get("customer_phone") or row.get("contact_first_name") or row.get("contact_last_name")):
            created_contact = bool(contact_id and not existing_contact)
            notes.append("created contact" if created_contact else "matched existing contact")

        service_request_id = self.create_service_request(row, customer_id, location_id, contact_id)
        return BlueFolderImportResult(
            row_number=row.get("source_row_number"),
            customer_id=customer_id,
            customer_location_id=location_id,
            customer_contact_id=contact_id,
            service_request_id=service_request_id,
            existing_service_request_id=existing_service_request_id,
            created_customer=created_customer,
            created_location=created_location,
            created_contact=created_contact,
            status="imported" if service_request_id else "failed",
            notes=notes,
        )

    def find_customer(self, row: dict[str, Any]) -> dict[str, Any] | None:
        email = (row.get("customer_email") or "").strip()
        phone = (row.get("customer_phone") or "").strip()
        name = (row.get("customer_name") or "").strip()
        for customer in self._list_customers():
            if email and customer.get("email", "").casefold() == email.casefold():
                return customer
            if phone and customer.get("phone", "") == phone:
                return customer
            if name and customer.get("name", "").casefold() == name.casefold():
                return customer
        return None

    def create_customer(self, row: dict[str, Any]) -> str | None:
        response = self.client.customers.add(**{k: v for k, v in self.build_customer_payload(row).items() if v})
        return self._extract_id(response, ("customerId", "id"))

    def create_service_request(
        self,
        row: dict[str, Any],
        customer_id: str | None,
        customer_location_id: str | None,
        customer_contact_id: str | None,
    ) -> str | None:
        payload = self.build_service_request_payload(
            row,
            customer_id=customer_id,
            customer_location_id=customer_location_id,
            customer_contact_id=customer_contact_id,
        )
        response = self.client.service_requests.add(**{k: v for k, v in payload.items() if v})
        return self._extract_id(response, ("serviceRequestId", "id"))

    def ensure_location(self, customer_id: str | None, row: dict[str, Any]) -> str | None:
        if not customer_id:
            return None
        location = self.find_location(customer_id, row)
        if location:
            return str(location.get("id") or "")
        if not row.get("address"):
            return None
        response = self.client.customer_locations.add(int(customer_id), **self.build_location_payload(row))
        return self._extract_id(response, ("customerLocationId", "id"))

    def ensure_contact(self, customer_id: str | None, location_id: str | None, row: dict[str, Any]) -> str | None:
        if not customer_id:
            return None
        contact = self.find_contact(customer_id, row)
        if contact:
            return str(contact.get("id") or "")
        first_name = row.get("contact_first_name") or row.get("customer_name", "").split(" ", 1)[0]
        if not first_name and not row.get("customer_email") and not row.get("customer_phone"):
            return None
        response = self.client.customer_contacts.add(
            int(customer_id),
            **self.build_contact_payload(row, location_id=location_id),
        )
        return self._extract_id(response, ("id", "customerContactId"))

    def find_location(self, customer_id: str | None, row: dict[str, Any]) -> dict[str, Any] | None:
        if not customer_id:
            return None
        address = (row.get("address") or "").casefold()
        city = (row.get("city") or "").casefold()
        zip_code = (row.get("zip") or "").strip()
        try:
            locations = self.client.customer_locations.get_by_customer_id(int(customer_id))
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return None
        for location in locations:
            if address and location.get("address", "").casefold() != address:
                continue
            if city and location.get("city", "").casefold() != city:
                continue
            if zip_code and str(location.get("zip") or "").strip() != zip_code:
                continue
            return location
        return None

    def find_contact(self, customer_id: str | None, row: dict[str, Any]) -> dict[str, Any] | None:
        if not customer_id:
            return None
        email = (row.get("customer_email") or "").casefold()
        phone = (row.get("customer_phone") or "").strip()
        full_name = " ".join(part for part in [row.get("contact_first_name"), row.get("contact_last_name")] if part).casefold()
        try:
            contacts = self.client.customer_contacts.list_for_customer(int(customer_id))
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return None
        for contact in contacts:
            contact_name = " ".join(part for part in [contact.get("firstName"), contact.get("lastName")] if part).casefold()
            if email and (contact.get("email") or "").casefold() == email:
                return contact
            if phone and str(contact.get("phone") or "").strip() == phone:
                return contact
            if full_name and contact_name == full_name:
                return contact
        return None

    def find_service_request_by_external_id(self, external_id: str | None) -> str | None:
        if not external_id:
            return None
        return self._list_service_requests_by_external_id().get(str(external_id).strip())

    def build_customer_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "customerName": row.get("customer_name"),
            "customerType": row.get("customer_type") or self.settings.service_smith_default_customer_type,
            "email": row.get("customer_email"),
            "phone": row.get("customer_phone"),
        }

    def build_location_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "locationName": row.get("location_name") or row.get("customer_name"),
            "addressStreet": row.get("address"),
            "addressCity": row.get("city"),
            "addressState": row.get("state"),
            "addressPostalCode": row.get("zip"),
        }

    def build_contact_payload(self, row: dict[str, Any], location_id: str | None) -> dict[str, Any]:
        first_name = row.get("contact_first_name") or row.get("customer_name", "").split(" ", 1)[0]
        last_name = row.get("contact_last_name") or (
            row.get("customer_name", "").split(" ", 1)[1] if " " in row.get("customer_name", "") else ""
        )
        return {
            "firstName": first_name,
            "lastName": last_name,
            "title": row.get("contact_title") or self.settings.service_smith_default_contact_title,
            "email": row.get("customer_email"),
            "phone": row.get("customer_phone"),
            "customerLocationId": location_id,
        }

    def build_service_request_payload(
        self,
        row: dict[str, Any],
        *,
        customer_id: str | None,
        customer_location_id: str | None,
        customer_contact_id: str | None,
    ) -> dict[str, Any]:
        return {
            "customerId": customer_id,
            "customerLocationId": customer_location_id,
            "customerContactId": customer_contact_id,
            "subject": row.get("subject"),
            "description": row.get("description") or row.get("subject"),
            "priority": row.get("priority") or self.settings.service_smith_default_sr_priority,
            "status": row.get("status") or self.settings.service_smith_default_sr_status,
            "externalId": row.get("external_id"),
            "customerLocationStreetAddress": row.get("address"),
            "customerLocationCity": row.get("city"),
            "customerLocationState": row.get("state"),
            "customerLocationPostalCode": row.get("zip"),
        }

    def _list_customers(self) -> list[dict[str, str]]:
        if self._customer_cache is not None:
            return self._customer_cache
        try:
            xml = self.client.customers.list({})
        except (AttributeError, TypeError, ValueError, RuntimeError):
            self._customer_cache = []
            return self._customer_cache
        customers: list[dict[str, str]] = []
        if isinstance(xml, ET.Element):
            for node in xml.findall(".//customer"):
                customers.append(
                    {
                        "id": node.findtext("customerId") or node.findtext("id") or "",
                        "customerId": node.findtext("customerId") or node.findtext("id") or "",
                        "name": node.findtext("customerName") or "",
                        "email": node.findtext("email") or "",
                        "phone": node.findtext("phone") or node.findtext("phoneNumber") or "",
                    }
                )
        self._customer_cache = customers
        return customers

    def _list_service_requests_by_external_id(self) -> dict[str, str]:
        if self._service_request_cache is not None:
            return self._service_request_cache
        end = date.today()
        start = end - timedelta(days=365)
        try:
            service_requests = self.client.service_requests.list_for_range(
                f"{start:%Y.%m.%d} 12:00 AM",
                f"{end:%Y.%m.%d} 11:59 PM",
            )
        except (AttributeError, TypeError, ValueError, RuntimeError):
            self._service_request_cache = {}
            return self._service_request_cache
        cache: dict[str, str] = {}
        for item in service_requests:
            if not isinstance(item, dict):
                continue
            external_id = item.get("externalId") or item.get("external_id")
            sr_id = item.get("id")
            if external_id and sr_id:
                cache[str(external_id).strip()] = str(sr_id)
        self._service_request_cache = cache
        return cache

    def _build_client(self, resolved_path: Path) -> object:
        with TemporarySysPath(resolved_path), _temporary_bluefolder_env(
            api_key=self.settings.bluefolder_api_key,
            account_name=self.settings.bluefolder_account_name,
            base_url=self.settings.bluefolder_base_url,
            host_header=self.settings.bluefolder_host_header,
            verify_ssl=self.settings.bluefolder_verify_ssl,
            timeout_seconds=self.settings.bluefolder_timeout_seconds,
        ):
            module = import_module_from_path(
                "bluefolder_api.client",
                resolved_path,
                reset_packages=("bluefolder_api",),
            )
            client_class = getattr(module, "BlueFolderClient")
            return client_class(base_url=(self.settings.bluefolder_base_url or None))


def model_to_payload(model: BlueFolderImportResult | BlueFolderImportPlan | BlueFolderPayloadPreview) -> dict[str, Any]:
    data = asdict(model)
    for key, value in list(data.items()):
        if isinstance(value, list):
            data[key] = list(value)
    return data


class _temporary_bluefolder_env:
    def __init__(
        self,
        *,
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

    def __exit__(self, exc_type, exc, tb) -> None:
        for key, previous in self.previous.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def extract_id(response: Any, candidate_tags: tuple[str, ...]) -> str | None:
    if response is None:
        return None
    if isinstance(response, dict):
        for tag in candidate_tags:
            value = response.get(tag)
            if value:
                return str(value)
        return None
    for tag in candidate_tags:
        try:
            value = response.findtext(f".//{tag}")
        except Exception:
            value = None
        if value:
            return str(value)
    return None


ServiceSmithBlueFolderClient._extract_id = staticmethod(extract_id)
