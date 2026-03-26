"""Shared helpers for file-backed stores."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically replace a text file while keeping a .bak copy of the prior version."""
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    backup_path = path.with_name(f"{path.name}.bak")

    try:
        with os.fdopen(temp_fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        if path.exists():
            os.replace(path, backup_path)

        try:
            os.replace(temp_path, path)
        except Exception:
            if backup_path.exists() and not path.exists():
                os.replace(backup_path, path)
            raise
    finally:
        if temp_path.exists():
            temp_path.unlink()
