"""Shared import-path context helpers for local adapter modules."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import TracebackType

_PACKAGE_ROOTS: dict[str, str] = {}


class TemporarySysPath:
    """Context manager that temporarily prepends a path to ``sys.path``."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def __enter__(self) -> None:
        if self.path not in sys.path:
            sys.path.insert(0, self.path)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            sys.path.remove(self.path)
        except ValueError:
            pass


def import_module_from_path(module_name: str, path: Path, *, reset_packages: tuple[str, ...] = ()):
    """Import a module from a local path, resetting cached package trees only when the root changes."""
    resolved_root = str(path.expanduser().resolve())
    should_reset = any(_PACKAGE_ROOTS.get(package) != resolved_root for package in reset_packages)
    if should_reset:
        package_prefixes = tuple(reset_packages)
        for loaded_name in list(sys.modules):
            if any(loaded_name == package or loaded_name.startswith(f"{package}.") for package in package_prefixes):
                sys.modules.pop(loaded_name, None)
        for package in package_prefixes:
            _PACKAGE_ROOTS[package] = resolved_root

    with TemporarySysPath(path):
        importlib.invalidate_caches()
        return importlib.import_module(module_name)
