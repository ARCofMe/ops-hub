"""Pytest configuration for Ops Hub."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    """Keep the live project .env from leaking into tests."""
    monkeypatch.chdir(tmp_path)
