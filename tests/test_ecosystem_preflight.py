"""Ecosystem preflight tests."""

from __future__ import annotations

import json
from pathlib import Path

from ops_hub.ecosystem_preflight import PreflightItem, build_preflight_report, has_blockers, main, render_json_report, render_report


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_preflight_reports_ready_local_web_and_backend_config(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
        OPS_HUB_TECHNICIAN_API_HOST=ops.example.com
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=https://parts.example.com
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        """,
    )
    for name in ("milestones.md", "frontend-architecture.md", "fielddesk-web-wrapper.md", "dispatch-guide.md", "parts-guide.md"):
        _write(tmp_path / "ops-hub" / "docs" / name, f"# {name}")

    report = build_preflight_report(tmp_path)

    assert not has_blockers(report)
    assert "[MANUAL] FieldDesk" in render_report(report)
    assert "[OK] Ecosystem: Frontend architecture" in render_report(report)
    assert "[OK] RouteDesk: VITE_OPS_HUB_API_BASE URL format" in render_report(report)


def test_preflight_flags_template_values_as_blockers(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env.example",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=false
        OPS_HUB_TECHNICIAN_API_TOKEN=
        OPS_HUB_BLUEFOLDER_API_KEY=
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=
        OPS_HUB_BLUEFOLDER_BASE_URL=
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={}
        OPS_HUB_TECHNICIAN_API_HOST=127.0.0.1
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.example",
        """
        VITE_OPS_HUB_API_BASE=http://127.0.0.1:8787
        VITE_OPS_HUB_API_TOKEN=replace-me
        VITE_DISPATCHER_ID=replace-me
        VITE_PARTSAPP_URL=http://127.0.0.1:4176
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.example",
        """
        VITE_OPS_HUB_API_BASE=http://127.0.0.1:8787
        VITE_OPS_HUB_API_TOKEN=replace-me
        VITE_PARTS_USER_ID=replace-me
        VITE_ROUTEDESK_URL=http://127.0.0.1:4175
        """,
    )

    report = build_preflight_report(tmp_path)
    rendered = render_report(report)

    assert has_blockers(report)
    assert "[WARN] OpsHub: Configuration file - using template .env.example" in rendered
    assert "OPS_HUB_TECHNICIAN_API_TOKEN is missing or placeholder" in rendered
    assert "VITE_OPS_HUB_API_TOKEN is missing or placeholder" in rendered


def test_preflight_flags_missing_technician_api_host(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
        OPS_HUB_TECHNICIAN_API_HOST=
        """,
    )

    rendered = render_report(build_preflight_report(tmp_path))

    assert "[FAIL] OpsHub: Technician API host" in rendered


def test_preflight_flags_malformed_web_urls(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
        OPS_HUB_TECHNICIAN_API_HOST=ops.example.com
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=parts.example.com
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        """,
    )

    rendered = render_report(build_preflight_report(tmp_path))

    assert "[FAIL] RouteDesk: VITE_OPS_HUB_API_BASE URL format" in rendered
    assert "[FAIL] RouteDesk: VITE_PARTSAPP_URL URL format" in rendered


def test_json_report_is_machine_readable() -> None:
    payload = json.loads(
        render_json_report(
            [
                PreflightItem(scope="OpsHub", status="ok", label="Backend", detail="ready"),
                PreflightItem(scope="FieldDesk", status="manual", label="Tablet", detail="check device"),
            ]
        )
    )

    assert payload["summary"] == {"fail": 0, "manual": 1, "ok": 1, "warn": 0}
    assert payload["scopes"]["FieldDesk"]["manual"] == 1
    assert payload["items"][1]["scope"] == "FieldDesk"


def test_strict_mode_treats_warnings_and_manual_checks_as_blockers() -> None:
    report = [
        PreflightItem(scope="OpsHub", status="ok", label="Backend", detail="ready"),
        PreflightItem(scope="FieldDesk", status="manual", label="Tablet", detail="check device"),
    ]

    assert not has_blockers(report)
    assert has_blockers(report, strict=True)


def test_cli_strict_mode_returns_failure_for_manual_checks(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
        OPS_HUB_TECHNICIAN_API_HOST=ops.example.com
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=https://parts.example.com
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        """,
    )
    for name in ("milestones.md", "frontend-architecture.md", "fielddesk-web-wrapper.md", "dispatch-guide.md", "parts-guide.md"):
        _write(tmp_path / "ops-hub" / "docs" / name, f"# {name}")

    assert main(["--root", str(tmp_path), "--strict"]) == 1


def test_preflight_validates_exported_fielddesk_preferences(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
        OPS_HUB_TECHNICIAN_API_HOST=ops.example.com
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=https://parts.example.com
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        """,
    )
    for name in ("milestones.md", "frontend-architecture.md", "fielddesk-web-wrapper.md", "dispatch-guide.md", "parts-guide.md"):
        _write(tmp_path / "ops-hub" / "docs" / name, f"# {name}")
    prefs = tmp_path / "fielddesk.xml"
    _write(
        prefs,
        """
        <map>
            <string name="backend_mode">OPS_HUB</string>
            <string name="ops_hub_base_url">https://ops.example.com</string>
            <string name="ops_hub_api_key">secret</string>
            <string name="tech_id">13051</string>
            <string name="route_desk_url">https://route.example.com</string>
            <string name="parts_desk_url">https://parts.example.com</string>
        </map>
        """,
    )

    report = build_preflight_report(tmp_path, fielddesk_prefs=prefs)

    assert not has_blockers(report, strict=True)
    rendered = render_report(report)
    assert "[OK] FieldDesk: RouteDesk handoff URL" in rendered
    assert "[OK] FieldDesk: PartsDesk handoff URL" in rendered


def test_preflight_flags_malformed_fielddesk_preference_urls(tmp_path: Path) -> None:
    prefs = tmp_path / "fielddesk.xml"
    _write(
        prefs,
        """
        <map>
            <string name="backend_mode">OPS_HUB</string>
            <string name="ops_hub_base_url">ops.example.com</string>
            <string name="ops_hub_api_key">secret</string>
            <string name="tech_id">13051</string>
            <string name="route_desk_url">route.example.com</string>
            <string name="parts_desk_url">https://parts.example.com</string>
        </map>
        """,
    )

    rendered = render_report(build_preflight_report(tmp_path, fielddesk_prefs=prefs))

    assert "[FAIL] FieldDesk: OpsHub base URL" in rendered
    assert "[WARN] FieldDesk: RouteDesk handoff URL" in rendered
    assert "[OK] FieldDesk: PartsDesk handoff URL" in rendered


def test_preflight_rejects_credentialed_urls(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
        OPS_HUB_TECHNICIAN_API_HOST=ops.example.com
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://user:pass@ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=https://parts.example.com
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        """,
    )

    rendered = render_report(build_preflight_report(tmp_path))

    assert "[FAIL] RouteDesk: VITE_OPS_HUB_API_BASE URL format" in rendered


def test_preflight_flags_direct_bluefolder_tablet_mode(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
        OPS_HUB_TECHNICIAN_API_HOST=ops.example.com
        """,
    )
    _write(tmp_path / "dispatch-app" / ".env.local", "VITE_OPS_HUB_API_BASE=x\nVITE_OPS_HUB_API_TOKEN=x\nVITE_DISPATCHER_ID=x\nVITE_PARTSAPP_URL=x\n")
    _write(tmp_path / "parts-app" / ".env.local", "VITE_OPS_HUB_API_BASE=x\nVITE_OPS_HUB_API_TOKEN=x\nVITE_PARTS_USER_ID=x\nVITE_ROUTEDESK_URL=x\n")
    prefs = tmp_path / "fielddesk.xml"
    _write(
        prefs,
        """
        <map>
            <string name="backend_mode">BLUEFOLDER_DIRECT</string>
            <string name="tech_id">13051</string>
        </map>
        """,
    )

    rendered = render_report(build_preflight_report(tmp_path, fielddesk_prefs=prefs))

    assert "[FAIL] FieldDesk: Backend mode" in rendered
    assert "[FAIL] FieldDesk: OpsHub base URL" in rendered
