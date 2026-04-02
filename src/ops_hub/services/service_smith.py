"""Ops Hub intake-analysis service migrated from ServiceSmith."""

from __future__ import annotations

from dataclasses import dataclass
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
from ops_hub.services.service_smith_importer import load_rows, preview_rows, read_headers, select_rows, validate_rows


@dataclass(slots=True)
class ServiceSmithService:
    """Spreadsheet intake helpers exposed through Ops Hub."""

    settings: Settings

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
