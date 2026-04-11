"""Ecosystem preflight tests."""

from __future__ import annotations

from pathlib import Path

from ops_hub.ecosystem_preflight import PreflightItem, build_preflight_report, has_blockers, main, render_report


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
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=https://parts.example.com
        VITE_FIELDDESK_URL=fielddesk://open
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        VITE_FIELDDESK_URL=fielddesk://open
        """,
    )

    report = build_preflight_report(tmp_path)

    assert not has_blockers(report)
    assert "[MANUAL] FieldDesk" in render_report(report)


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
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.example",
        """
        VITE_OPS_HUB_API_BASE=http://127.0.0.1:8787
        VITE_OPS_HUB_API_TOKEN=replace-me
        VITE_DISPATCHER_ID=replace-me
        VITE_PARTSAPP_URL=http://127.0.0.1:4176
        VITE_FIELDDESK_URL=
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.example",
        """
        VITE_OPS_HUB_API_BASE=http://127.0.0.1:8787
        VITE_OPS_HUB_API_TOKEN=replace-me
        VITE_PARTS_USER_ID=replace-me
        VITE_ROUTEDESK_URL=http://127.0.0.1:4175
        VITE_FIELDDESK_URL=
        """,
    )

    report = build_preflight_report(tmp_path)
    rendered = render_report(report)

    assert has_blockers(report)
    assert "[WARN] OpsHub: Configuration file - using template .env.example" in rendered
    assert "OPS_HUB_TECHNICIAN_API_TOKEN is missing or placeholder" in rendered
    assert "VITE_OPS_HUB_API_TOKEN is missing or placeholder" in rendered


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
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=https://parts.example.com
        VITE_FIELDDESK_URL=fielddesk://open
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        VITE_FIELDDESK_URL=fielddesk://open
        """,
    )

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
        """,
    )
    _write(
        tmp_path / "dispatch-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_DISPATCHER_ID=42
        VITE_PARTSAPP_URL=https://parts.example.com
        VITE_FIELDDESK_URL=fielddesk://open
        """,
    )
    _write(
        tmp_path / "parts-app" / ".env.local",
        """
        VITE_OPS_HUB_API_BASE=https://ops.example.com
        VITE_OPS_HUB_API_TOKEN=secret
        VITE_PARTS_USER_ID=77
        VITE_ROUTEDESK_URL=https://route.example.com
        VITE_FIELDDESK_URL=fielddesk://open
        """,
    )
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


def test_preflight_flags_direct_bluefolder_tablet_mode(tmp_path: Path) -> None:
    _write(
        tmp_path / "ops-hub" / ".env",
        """
        OPS_HUB_ENABLE_TECHNICIAN_API=true
        OPS_HUB_TECHNICIAN_API_TOKEN=secret
        OPS_HUB_BLUEFOLDER_API_KEY=key
        OPS_HUB_BLUEFOLDER_ACCOUNT_NAME=acme
        OPS_HUB_TECHNICIAN_BLUEFOLDER_USER_MAP={"42":13051}
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
