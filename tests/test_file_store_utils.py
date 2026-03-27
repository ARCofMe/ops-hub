"""Tests for shared file-store helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ops_hub.services import file_store_utils


def test_atomic_write_text_creates_parent_and_writes_new_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "state.json"

    file_store_utils.atomic_write_text(target, '{"ok": true}')

    assert target.read_text(encoding="utf-8") == '{"ok": true}'
    assert not target.with_name("state.json.bak").exists()


def test_atomic_write_text_creates_backup_when_overwriting(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_text('{"old": true}', encoding="utf-8")

    file_store_utils.atomic_write_text(target, '{"new": true}')

    assert target.read_text(encoding="utf-8") == '{"new": true}'
    assert target.with_name("state.json.bak").read_text(encoding="utf-8") == '{"old": true}'


def test_atomic_write_text_restores_original_when_final_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    target.write_text('{"old": true}', encoding="utf-8")
    original_replace = os.replace
    replace_calls = 0

    def fake_replace(src, dst) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("disk full")
        original_replace(src, dst)

    monkeypatch.setattr(file_store_utils.os, "replace", fake_replace)

    with pytest.raises(OSError, match="disk full"):
        file_store_utils.atomic_write_text(target, '{"new": true}')

    assert target.read_text(encoding="utf-8") == '{"old": true}'
    assert not any(child.name.startswith(".state.json.") and child.suffix == ".tmp" for child in tmp_path.iterdir())
