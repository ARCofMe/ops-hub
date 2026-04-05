from __future__ import annotations

import json

from ops_hub.core.config import Settings
from ops_hub.services.operator_directory import TechnicianDirectoryService
from ops_hub.services.operator_mapping_store import OperatorMappingStore


def test_mapping_records_include_member_export_identity(tmp_path) -> None:
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    (exports_dir / "discord_members_member_map_20260405T180000Z.json").write_text(
        json.dumps(
            {
                "members": [
                    {
                        "discord_user_id": "42",
                        "username": "dispatch.user",
                        "display_name": "Dispatch Dave",
                        "global_name": "dave",
                        "role_names": ["Dispatch"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        discord_token="token",
        member_export_path=str(exports_dir / "discord_members.json"),
        technician_bluefolder_user_map={42: 9001},
    )
    service = TechnicianDirectoryService(settings=settings, store=OperatorMappingStore())

    records = service.mapping_records()

    assert len(records) == 1
    assert records[0].display_name == "Dispatch Dave"
    assert records[0].username == "dispatch.user"
    assert records[0].role_names == ("Dispatch",)
    assert service.display_label(42) == "Dispatch Dave"
    assert service.technician_display_label(bluefolder_user_id=9001) == "Dispatch Dave"
