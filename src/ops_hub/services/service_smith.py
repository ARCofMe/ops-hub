"""Ops Hub intake-analysis service migrated from ServiceSmith."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from ops_hub.core.config import Settings
from ops_hub.services.service_smith_bluefolder import ServiceSmithBlueFolderClient, model_to_payload
from ops_hub.services.service_smith_formats import (
    SpreadsheetAdapter,
    analyze_headers,
    detect_adapter_matches,
    get_adapter,
    list_adapters,
    load_field_map_override,
    merge_field_maps,
)
from ops_hub.services.service_smith_importer import (
    load_rows,
    normalize_row_for_import,
    preview_rows,
    read_headers,
    select_rows,
    validate_rows,
)
from ops_hub.services.service_smith_profile_store import IntakeProfileRecord, ServiceSmithProfileStore


@dataclass(slots=True)
class ServiceSmithService:
    """Spreadsheet intake helpers exposed through Ops Hub."""

    settings: Settings
    profile_store: ServiceSmithProfileStore | None = None

    def list_formats_payload(self) -> dict[str, object]:
        adapters = list_adapters()
        return {
            "items": [
                {
                    "name": adapter.name,
                    "description": adapter.description,
                    "headers": list(adapter.field_map.values()),
                }
                for adapter in adapters
            ]
        }

    def list_profiles_payload(self) -> dict[str, object]:
        """Return saved intake profiles."""
        profiles = self.profile_store.load() if self.profile_store else []
        return {
            "items": [self._profile_payload(profile) for profile in sorted(profiles, key=lambda item: item.name.lower())]
        }

    def save_profile_payload(
        self,
        *,
        name: str,
        format_name: str = "default",
        field_map_path: str | None = None,
        row_start: int | None = None,
        row_end: int | None = None,
        limit: int | None = 25,
        duplicate_mode: str = "skip",
        preview_mode: str = "plan",
        fail_fast: bool = False,
        actor_user_id: int | None = None,
    ) -> dict[str, object]:
        """Create or update one saved intake profile."""
        if not self.profile_store:
            raise RuntimeError("ServiceSmith profile storage is not configured.")

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name is required.")

        records = self.profile_store.load()
        record = IntakeProfileRecord(
            name=normalized_name,
            format_name=format_name or "default",
            field_map_path=field_map_path or None,
            row_start=row_start,
            row_end=row_end,
            limit=limit,
            duplicate_mode=duplicate_mode or "skip",
            preview_mode=preview_mode or "plan",
            fail_fast=fail_fast,
            updated_by_user_id=actor_user_id,
        )
        remaining = [existing for existing in records if existing.name.lower() != normalized_name.lower()]
        remaining.append(record)
        self.profile_store.save(sorted(remaining, key=lambda item: item.name.lower()))
        return {"success": True, "message": f"Saved intake profile {normalized_name}.", "profile": self._profile_payload(record)}

    def delete_profile_payload(self, *, name: str) -> dict[str, object]:
        """Delete one saved intake profile."""
        if not self.profile_store:
            raise RuntimeError("ServiceSmith profile storage is not configured.")

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name is required.")

        records = self.profile_store.load()
        remaining = [existing for existing in records if existing.name.lower() != normalized_name.lower()]
        if len(remaining) == len(records):
            raise ValueError(f"No intake profile found for {normalized_name}.")
        self.profile_store.save(remaining)
        return {"success": True, "message": f"Deleted intake profile {normalized_name}.", "name": normalized_name}

    def analyze_spreadsheet_payload(
        self,
        *,
        spreadsheet_path: str,
        format_name: str = "default",
        field_map_path: str | None = None,
        row_start: int | None = None,
        row_end: int | None = None,
        limit: int | None = 25,
    ) -> dict[str, object]:
        spreadsheet = Path(spreadsheet_path).expanduser()
        if not spreadsheet.exists():
            raise ValueError(f"Spreadsheet path does not exist: {spreadsheet}")

        adapter = get_adapter(format_name)
        field_map = dict(adapter.field_map)
        if field_map_path:
            field_map = merge_field_maps(field_map, load_field_map_override(field_map_path))

        headers = read_headers(spreadsheet)
        header_analysis = analyze_headers(headers, field_map)
        rows = select_rows(
            load_rows(spreadsheet, field_map),
            row_start=row_start,
            row_end=row_end,
            limit=limit,
        )
        issues = validate_rows(rows)
        return {
            "spreadsheetPath": str(spreadsheet),
            "selectedAdapter": self._adapter_payload(adapter),
            "headerAnalysis": header_analysis,
            "adapterMatches": detect_adapter_matches(headers),
            "headers": headers,
            "rowCount": len(rows),
            "previewRows": preview_rows(rows, limit=5),
            "validationIssues": issues,
            "selectedRows": {
                "rowStart": row_start,
                "rowEnd": row_end,
                "limit": limit,
            },
        }

    def preview_import_payload(
        self,
        *,
        spreadsheet_path: str,
        format_name: str = "default",
        field_map_path: str | None = None,
        duplicate_mode: str = "skip",
        preview_mode: str = "plan",
        row_start: int | None = None,
        row_end: int | None = None,
        limit: int | None = 25,
    ) -> dict[str, object]:
        client = ServiceSmithBlueFolderClient(self.settings)
        rows = self._selected_rows(
            spreadsheet_path=spreadsheet_path,
            format_name=format_name,
            field_map_path=field_map_path,
            row_start=row_start,
            row_end=row_end,
            limit=limit,
        )
        if preview_mode == "payload_preview":
            items = [model_to_payload(client.preview_payloads(row, duplicate_mode=duplicate_mode)) for row in rows]
        else:
            items = [model_to_payload(client.plan_import(row, duplicate_mode=duplicate_mode)) for row in rows]
        return {
            "spreadsheetPath": str(Path(spreadsheet_path).expanduser()),
            "previewMode": preview_mode,
            "duplicateMode": duplicate_mode,
            "rowCount": len(rows),
            "items": items,
        }

    def import_spreadsheet_payload(
        self,
        *,
        spreadsheet_path: str,
        format_name: str = "default",
        field_map_path: str | None = None,
        duplicate_mode: str = "skip",
        row_start: int | None = None,
        row_end: int | None = None,
        limit: int | None = None,
        fail_fast: bool = False,
    ) -> dict[str, object]:
        client = ServiceSmithBlueFolderClient(self.settings)
        rows = self._selected_rows(
            spreadsheet_path=spreadsheet_path,
            format_name=format_name,
            field_map_path=field_map_path,
            row_start=row_start,
            row_end=row_end,
            limit=limit,
        )
        results: list[dict[str, object]] = []
        for row in rows:
            result = model_to_payload(client.ensure_customer_and_import(row, duplicate_mode=duplicate_mode))
            results.append(result)
            if fail_fast and result.get("status") != "imported":
                break
        return {
            "spreadsheetPath": str(Path(spreadsheet_path).expanduser()),
            "duplicateMode": duplicate_mode,
            "failFast": fail_fast,
            "rowCount": len(rows),
            "results": results,
            "summary": self._summarize_results(results),
        }

    def preview_manual_service_request_payload(
        self,
        *,
        request: dict[str, object],
        duplicate_mode: str = "error",
    ) -> dict[str, object]:
        """Plan one manually entered service request before writing to BlueFolder."""
        row = self._manual_request_row(request)
        issues = validate_rows([row])
        client = ServiceSmithBlueFolderClient(self.settings)
        plan = model_to_payload(client.plan_import(row, duplicate_mode=duplicate_mode))
        payload_preview = model_to_payload(client.preview_payloads(row, duplicate_mode=duplicate_mode))
        return {
            "success": True,
            "mode": "manual_service_request",
            "duplicateMode": duplicate_mode,
            "row": row,
            "validationIssues": issues,
            "blockingIssueCount": len([item for item in issues if item.get("level") == "error"]),
            "plan": plan,
            "payloadPreview": payload_preview,
        }

    def import_manual_service_request_payload(
        self,
        *,
        request: dict[str, object],
        duplicate_mode: str = "error",
        confirmed: bool = False,
        allow_validation_override: bool = False,
    ) -> dict[str, object]:
        """Create one manually entered service request after preview confirmation."""
        if not confirmed:
            raise ValueError("Manual service request import requires preview confirmation.")

        row = self._manual_request_row(request)
        issues = validate_rows([row])
        blocking_issues = [item for item in issues if item.get("level") == "error"]
        if blocking_issues and not allow_validation_override:
            raise ValueError("Manual service request has blocking validation errors.")

        client = ServiceSmithBlueFolderClient(self.settings)
        result = model_to_payload(client.ensure_customer_and_import(row, duplicate_mode=duplicate_mode))
        return {
            "success": result.get("status") == "imported",
            "mode": "manual_service_request",
            "duplicateMode": duplicate_mode,
            "row": row,
            "validationIssues": issues,
            "result": result,
            "summary": self._summarize_results([result]),
        }

    @staticmethod
    def _adapter_payload(adapter: SpreadsheetAdapter) -> dict[str, object]:
        return {
            "name": adapter.name,
            "description": adapter.description,
            "fieldMap": adapter.field_map,
        }

    def _selected_rows(
        self,
        *,
        spreadsheet_path: str,
        format_name: str,
        field_map_path: str | None,
        row_start: int | None,
        row_end: int | None,
        limit: int | None,
    ) -> list[dict[str, str]]:
        spreadsheet = Path(spreadsheet_path).expanduser()
        if not spreadsheet.exists():
            raise ValueError(f"Spreadsheet path does not exist: {spreadsheet}")
        adapter = get_adapter(format_name)
        field_map = dict(adapter.field_map)
        if field_map_path:
            field_map = merge_field_maps(field_map, load_field_map_override(field_map_path))
        return select_rows(
            load_rows(spreadsheet, field_map),
            row_start=row_start,
            row_end=row_end,
            limit=limit,
        )

    @staticmethod
    def _profile_payload(profile: IntakeProfileRecord) -> dict[str, object]:
        return {
            "name": profile.name,
            "formatName": profile.format_name,
            "fieldMapPath": profile.field_map_path,
            "rowStart": profile.row_start,
            "rowEnd": profile.row_end,
            "limit": profile.limit,
            "duplicateMode": profile.duplicate_mode,
            "previewMode": profile.preview_mode,
            "failFast": profile.fail_fast,
            "updatedByUserId": profile.updated_by_user_id,
        }

    @staticmethod
    def _manual_request_row(request: dict[str, object]) -> dict[str, str]:
        row = {
            "customer_name": _first_value(request, "customer_name", "customerName"),
            "customer_email": _first_value(request, "customer_email", "customerEmail", "email"),
            "customer_phone": _first_value(request, "customer_phone", "customerPhone", "phone"),
            "customer_type": _first_value(request, "customer_type", "customerType"),
            "contact_first_name": _first_value(request, "contact_first_name", "contactFirstName"),
            "contact_last_name": _first_value(request, "contact_last_name", "contactLastName"),
            "contact_title": _first_value(request, "contact_title", "contactTitle"),
            "location_name": _first_value(request, "location_name", "locationName"),
            "address": _first_value(request, "address", "street", "addressStreet"),
            "city": _first_value(request, "city", "addressCity"),
            "state": _first_value(request, "state", "addressState"),
            "zip": _first_value(request, "zip", "postalCode", "addressPostalCode"),
            "subject": _first_value(request, "subject", "title"),
            "description": _first_value(request, "description", "details"),
            "priority": _first_value(request, "priority"),
            "status": _first_value(request, "status"),
            "external_id": _first_value(request, "external_id", "externalId"),
        }
        normalized = normalize_row_for_import(row, row_number="manual")
        if not normalized.get("external_id"):
            normalized["external_id"] = _manual_external_id(normalized)
        return normalized

    @staticmethod
    def _summarize_results(results: list[dict[str, object]]) -> dict[str, int]:
        summary: dict[str, int] = {"total": len(results)}
        for item in results:
            status = str(item.get("status") or "")
            if status:
                key = f"status:{status}"
                summary[key] = summary.get(key, 0) + 1
            if item.get("created_customer"):
                summary["created_customer"] = summary.get("created_customer", 0) + 1
            if item.get("created_location"):
                summary["created_location"] = summary.get("created_location", 0) + 1
            if item.get("created_contact"):
                summary["created_contact"] = summary.get("created_contact", 0) + 1
        return summary


def _first_value(source: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def _manual_external_id(row: dict[str, str]) -> str:
    identity = "|".join(
        [
            row.get("customer_name", "").casefold(),
            row.get("address", "").casefold(),
            row.get("city", "").casefold(),
            row.get("state", "").casefold(),
            row.get("zip", "").casefold(),
            (row.get("subject") or row.get("description") or "").casefold(),
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"routedesk-manual-{digest}"
