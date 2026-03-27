"""Tests for shared adapter import-path helpers."""

from __future__ import annotations

import sys
from pathlib import Path

from ops_hub.integrations.import_context import TemporarySysPath


def test_temporary_sys_path_prepends_and_removes_path(tmp_path: Path) -> None:
    path = tmp_path / "lib"
    original_sys_path = list(sys.path)

    with TemporarySysPath(path):
        assert sys.path[0] == str(path)

    assert sys.path == original_sys_path


def test_temporary_sys_path_ignores_missing_path_on_exit(tmp_path: Path) -> None:
    path = tmp_path / "lib"

    with TemporarySysPath(path):
        sys.path.remove(str(path))

    assert str(path) not in sys.path
