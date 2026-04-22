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
