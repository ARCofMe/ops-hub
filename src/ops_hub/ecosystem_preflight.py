"""Local presentation preflight checks for the OpsHub app ecosystem."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PLACEHOLDER_VALUES = {"", "replace-me", "changeme", "change-me", "todo", "none", "null"}


@dataclass(frozen=True)
class PreflightItem:
    """One presentation readiness check."""

    scope: str
    status: str
    label: str
    detail: str


def build_preflight_report(root: Path) -> list[PreflightItem]:
    """Return local ecosystem presentation checks without exposing secret values."""
    repo_root = root.resolve()
    items: list[PreflightItem] = []
    items.extend(_check_ops_hub(repo_root / "ops-hub"))
    items.extend(
        _check_web_app(
            repo_root / "dispatch-app",
            scope="RouteDesk",
            required_keys=("VITE_OPS_HUB_API_BASE", "VITE_OPS_HUB_API_TOKEN", "VITE_DISPATCHER_ID"),
            sibling_keys=("VITE_PARTSAPP_URL",),
            optional_sibling_keys=("VITE_FIELDDESK_URL",),
        )
    )
    items.extend(
        _check_web_app(
            repo_root / "parts-app",
            scope="PartsDesk",
            required_keys=("VITE_OPS_HUB_API_BASE", "VITE_OPS_HUB_API_TOKEN", "VITE_PARTS_USER_ID"),
            sibling_keys=("VITE_ROUTEDESK_URL",),
            optional_sibling_keys=("VITE_FIELDDESK_URL",),
        )
    )
    items.append(
        PreflightItem(
            scope="FieldDesk",
            status="manual",
            label="Tablet runtime settings",
            detail="Confirm backend mode, API key, technician ID, and workspace URLs on the tablet.",
        )
    )
    return items


def render_report(items: Iterable[PreflightItem]) -> str:
    """Render a report that is safe to paste into a release checklist."""
    rows = list(items)
    summary = {
        "fail": sum(1 for item in rows if item.status == "fail"),
        "warn": sum(1 for item in rows if item.status == "warn"),
        "manual": sum(1 for item in rows if item.status == "manual"),
        "ok": sum(1 for item in rows if item.status == "ok"),
    }
    lines = [
        "OpsHub Ecosystem Preflight",
        f"Summary: {summary['ok']} ok, {summary['warn']} warn, {summary['fail']} fail, {summary['manual']} manual",
        "",
    ]
    for item in rows:
        lines.append(f"[{item.status.upper()}] {item.scope}: {item.label} - {item.detail}")
    return "\n".join(lines)


def has_blockers(items: Iterable[PreflightItem], *, strict: bool = False) -> bool:
    """Return whether the report contains release blockers."""
    blocking_statuses = {"fail", "warn", "manual"} if strict else {"fail"}
    return any(item.status in blocking_statuses for item in items)


def _check_ops_hub(repo: Path) -> list[PreflightItem]:
    source, values = _load_env(repo, preferred=(".env", ".env.example"))
    items: list[PreflightItem] = [_source_check("OpsHub", source)]
    if source is None:
        return items

    items.append(_required("OpsHub", source, values, "OPS_HUB_TECHNICIAN_API_TOKEN", "Technician API token"))
    enabled = values.get("OPS_HUB_ENABLE_TECHNICIAN_API", "").strip().lower()
    items.append(
        PreflightItem(
            scope="OpsHub",
            status="ok" if enabled == "true" else "fail",
            label="Technician API enabled",
            detail="required for FieldDesk live workflow APIs",
        )
    )
    bluefolder_ready = not _is_placeholder(values.get("OPS_HUB_BLUEFOLDER_API_KEY")) and (
        not _is_placeholder(values.get("OPS_HUB_BLUEFOLDER_ACCOUNT_NAME"))
        or not _is_placeholder(values.get("OPS_HUB_BLUEFOLDER_BASE_URL"))
    )
    items.append(
        PreflightItem(
            scope="OpsHub",
            status="ok" if bluefolder_ready else "fail",
            label="BlueFolder connection",
            detail="API key plus account name or base URL must be configured",
        )
    )
    mapping_value = values.get("OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP", "")
    mapping_file = values.get("OPS_HUB_TECHNICIAN_MAPPING_FILE", "")
    items.append(
        PreflightItem(
            scope="OpsHub",
            status="ok" if mapping_value.strip() not in {"", "{}"} or not _is_placeholder(mapping_file) else "warn",
            label="Technician mapping",
            detail="map at least the demo technician before presenting FieldDesk",
        )
    )
    return items


def _check_web_app(
    repo: Path,
    *,
    scope: str,
    required_keys: tuple[str, ...],
    sibling_keys: tuple[str, ...],
    optional_sibling_keys: tuple[str, ...],
) -> list[PreflightItem]:
    source, values = _load_env(repo, preferred=(".env.local", ".env", ".env.example"))
    items: list[PreflightItem] = [_source_check(scope, source)]
    if source is None:
        return items

    for key in required_keys:
        items.append(_required(scope, source, values, key, key))
    for key in sibling_keys:
        items.append(_required(scope, source, values, key, key))
    for key in optional_sibling_keys:
        items.append(
            PreflightItem(
                scope=scope,
                status="ok" if not _is_placeholder(values.get(key)) else "warn",
                label=key,
                detail="optional but recommended for cross-device presentation handoff",
            )
        )
    return items


def _load_env(repo: Path, *, preferred: tuple[str, ...]) -> tuple[Path | None, dict[str, str]]:
    for name in preferred:
        path = repo / name
        if path.exists():
            return path, _parse_env(path)
    return None, {}


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _source_check(scope: str, source: Path | None) -> PreflightItem:
    if source is None:
        return PreflightItem(scope=scope, status="fail", label="Configuration file", detail="no .env file found")
    if source.name.endswith("example"):
        return PreflightItem(scope=scope, status="warn", label="Configuration file", detail=f"using template {source.name}")
    return PreflightItem(scope=scope, status="ok", label="Configuration file", detail=f"using {source.name}")


def _required(scope: str, source: Path, values: dict[str, str], key: str, label: str) -> PreflightItem:
    value = values.get(key)
    return PreflightItem(
        scope=scope,
        status="fail" if _is_placeholder(value) else "ok",
        label=label,
        detail=f"{key} {'is missing or placeholder' if _is_placeholder(value) else 'is set'} in {source.name}",
    )


def _is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in PLACEHOLDER_VALUES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local OpsHub ecosystem presentation readiness.")
    parser.add_argument("--root", type=Path, default=Path.cwd().parent, help="ARCoM workspace root containing app repos.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings and manual checks as blockers.")
    args = parser.parse_args(argv)
    items = build_preflight_report(args.root)
    print(render_report(items))
    return 1 if has_blockers(items, strict=args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
