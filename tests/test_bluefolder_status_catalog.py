import json
from pathlib import Path

from ops_hub.services.bluefolder_status_catalog import status_catalog_payload


def test_status_catalog_payload_counts_primary_surfaces(tmp_path: Path) -> None:
    (tmp_path / "bluefolder_status_inventory.json").write_text(
        json.dumps(
            {
                "service_request": {
                    "tenant_ui_status_options": [
                        "Need Parts/Schedule",
                        "Scheduled",
                        "Completed",
                    ]
                }
            }
        )
    )

    payload = status_catalog_payload(base_path=str(tmp_path))

    assert payload["knownCount"] == 3
    assert payload["categoryCounts"]["parts"] == 1
    assert payload["categoryCounts"]["scheduling"] == 1
    assert payload["categoryCounts"]["closed"] == 1
    assert payload["primarySurfaceCounts"]["partsdesk"] == 1
    assert payload["primarySurfaceCounts"]["routedesk"] == 1
    assert payload["primarySurfaceCounts"]["archive"] == 1
    assert payload["surfaceActions"][0] == {
        "surface": "partsdesk",
        "label": "PartsDesk",
        "count": 1,
        "action": "Review part-blocked and ordering statuses.",
    }


def test_status_catalog_payload_falls_back_to_observed_and_live_statuses(tmp_path: Path) -> None:
    (tmp_path / "bluefolder_status_inventory.json").write_text(
        json.dumps(
            {
                "service_request": {
                    "observed_status_values": [{"value": "New"}, {"value": "Completed"}],
                },
                "live_tenant_extract": {
                    "service_request": {
                        "distinct_statuses": [
                            {"value": "Need Parts/Schedule", "count": 2},
                            {"value": "completed", "count": 1},
                        ]
                    }
                },
            }
        )
    )

    payload = status_catalog_payload(base_path=str(tmp_path))

    assert payload["tenantStatusOptions"] == ["New", "Completed", "Need Parts/Schedule"]
    assert payload["categoryCounts"]["parts"] == 1
    assert payload["categoryCounts"]["closed"] == 1
