"""BlueFolder service-request status catalog loading and classification."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


def _inventory_path(base_path: str | None) -> Path | None:
    if not base_path:
        return None
    candidate = Path(base_path).expanduser() / "bluefolder_status_inventory.json"
    return candidate if candidate.exists() else None


@lru_cache(maxsize=8)
def _load_inventory(base_path: str | None) -> dict[str, object]:
    inventory_path = _inventory_path(base_path)
    if inventory_path is None:
        return {}
    try:
        return json.loads(inventory_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def tenant_status_options(*, base_path: str | None) -> list[str]:
    inventory = _load_inventory(base_path)
    service_request = inventory.get("service_request")
    if not isinstance(service_request, dict):
        return []
    values = _status_values_from_list(service_request.get("tenant_ui_status_options"))
    if values:
        return values
    values = _status_values_from_list(service_request.get("observed_status_values"))
    live_tenant = inventory.get("live_tenant_extract")
    if isinstance(live_tenant, dict):
        live_service_request = live_tenant.get("service_request")
        if isinstance(live_service_request, dict):
            values.extend(_status_values_from_list(live_service_request.get("distinct_statuses")))
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _status_values_from_list(raw_values: object) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    values: list[str] = []
    for entry in raw_values:
        if isinstance(entry, dict):
            value = entry.get("value")
        else:
            value = entry
        normalized = str(value or "").strip()
        if normalized:
            values.append(normalized)
    return values


def describe_service_request_status(
    service_request_status: str | None,
    *,
    base_path: str | None,
) -> dict[str, object]:
    raw = str(service_request_status or "").strip()
    normalized = raw.casefold()
    known_values = {value.casefold() for value in tenant_status_options(base_path=base_path)}

    is_closed = _is_closed_status(normalized)
    is_quote_needed = _is_quote_needed_status(normalized)
    is_active_parts = _is_active_parts_status(normalized)
    is_waiting_customer = _is_waiting_customer_status(normalized)
    is_scheduling = _is_scheduling_status(normalized)
    is_review = _is_review_status(normalized)
    category = _category_for_status(
        normalized,
        is_closed=is_closed,
        is_quote_needed=is_quote_needed,
        is_active_parts=is_active_parts,
        is_waiting_customer=is_waiting_customer,
        is_scheduling=is_scheduling,
        is_review=is_review,
    )

    return {
        "raw": raw or None,
        "normalized": normalized or None,
        "knownInTenantCatalog": bool(normalized and normalized in known_values),
        "category": category,
        "categoryLabel": _category_label(category),
        "isClosed": is_closed,
        "isOpen": bool(raw) and not is_closed,
        "isQuoteNeeded": is_quote_needed,
        "quoteSubtype": _quote_needed_subtype(normalized) if is_quote_needed else None,
        "isActiveParts": is_active_parts,
        "isWaitingCustomer": is_waiting_customer,
        "isScheduling": is_scheduling,
        "isReview": is_review,
        "primarySurface": _primary_surface(category),
    }


def status_catalog_payload(*, base_path: str | None) -> dict[str, object]:
    options = tenant_status_options(base_path=base_path)
    status_meta = [describe_service_request_status(value, base_path=base_path) for value in options]
    surface_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for item in status_meta:
        surface = str(item.get("primarySurface") or "ops_hub")
        category = str(item.get("category") or "other")
        surface_counts[surface] = surface_counts.get(surface, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "tenantStatusOptions": options,
        "knownCount": len(options),
        "categories": [
            {"key": "new", "label": "New"},
            {"key": "scheduling", "label": "Scheduling"},
            {"key": "parts", "label": "Parts"},
            {"key": "quote", "label": "Quote"},
            {"key": "waiting_customer", "label": "Waiting Customer"},
            {"key": "review", "label": "Review"},
            {"key": "closed", "label": "Closed"},
            {"key": "other", "label": "Other"},
        ],
        "categoryCounts": category_counts,
        "primarySurfaceCounts": surface_counts,
        "statusMeta": status_meta,
    }


def _is_closed_status(normalized: str) -> bool:
    return bool(normalized) and any(
        phrase in normalized
        for phrase in {"complete", "completed", "closed", "cancelled", "canceled", "resolved", "done"}
    )


def _is_quote_needed_status(normalized: str) -> bool:
    return bool(normalized) and ("quote needed" in normalized or normalized in {"needs quote", "quote"})


def _quote_needed_subtype(normalized: str) -> str:
    if any(token in normalized for token in ("landlord", "tenant")):
        return "landlord"
    if any(token in normalized for token in ("prepay", "pre-payment", "pre payment", "cod")):
        return "prepayment"
    return "customer"


def _is_active_parts_status(normalized: str) -> bool:
    return bool(normalized) and any(
        phrase in normalized
        for phrase in {
            "need parts",
            "needs parts",
            "parts/schedule",
            "waiting parts",
            "awaiting parts",
            "check tracking",
            "tracking",
            "backordered",
            "submit order",
            "order parts",
            "part ordered",
            "parts ordered",
            "part eta",
            "part received",
            "ready to schedule",
        }
    )


def _is_waiting_customer_status(normalized: str) -> bool:
    return bool(normalized) and any(
        phrase in normalized
        for phrase in {
            "waiting on cx",
            "waiting for payment",
            "waiting authorization",
            "call cx",
            "follow up",
            "left vm",
            "need to reschedule",
        }
    )


def _is_scheduling_status(normalized: str) -> bool:
    return bool(normalized) and any(
        phrase in normalized
        for phrase in {"scheduled", "schedule/left vm", "need to reschedule"}
    )


def _is_review_status(normalized: str) -> bool:
    return bool(normalized) and any(
        phrase in normalized
        for phrase in {
            "review",
            "triage",
            "engineering",
            "bos",
            "claim",
            "rc review",
            "tradecare",
            "whirlpool tbc",
            "saw requested",
            "sealed system",
        }
    )


def _category_for_status(
    normalized: str,
    *,
    is_closed: bool,
    is_quote_needed: bool,
    is_active_parts: bool,
    is_waiting_customer: bool,
    is_scheduling: bool,
    is_review: bool,
) -> str:
    if not normalized:
        return "other"
    if is_closed:
        return "closed"
    if is_quote_needed:
        return "quote"
    if is_active_parts:
        return "parts"
    if is_waiting_customer:
        return "waiting_customer"
    if is_scheduling:
        return "scheduling"
    if is_review:
        return "review"
    if normalized == "new" or "hold" in normalized:
        return "new"
    return "other"


def _category_label(category: str) -> str:
    return {
        "new": "New",
        "scheduling": "Scheduling",
        "parts": "Parts",
        "quote": "Quote",
        "waiting_customer": "Waiting Customer",
        "review": "Review",
        "closed": "Closed",
        "other": "Other",
    }.get(category, "Other")


def _primary_surface(category: str) -> str:
    return {
        "parts": "partsdesk",
        "scheduling": "routedesk",
        "quote": "routedesk",
        "waiting_customer": "routedesk",
        "review": "ops_hub",
        "new": "ops_hub",
        "closed": "archive",
        "other": "ops_hub",
    }.get(category, "ops_hub")
