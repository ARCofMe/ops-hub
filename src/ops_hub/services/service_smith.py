"""Ops Hub intake-analysis service migrated from ServiceSmith."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

    @staticmethod
    def _adapter_payload(adapter: SpreadsheetAdapter) -> dict[str, object]:
        return {
            "name": adapter.name,
            "description": adapter.description,
            "fieldMap": adapter.field_map,
        }
