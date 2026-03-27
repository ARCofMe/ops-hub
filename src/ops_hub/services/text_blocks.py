"""Small helpers for building Markdown response blocks."""

from __future__ import annotations


def section(title: str, *lines: str) -> list[str]:
    """Return a titled Markdown section, omitting empty lines."""
    result = [title]
    result.extend(line for line in lines if line)
    return result


def status_section(
    title: str,
    *,
    status: str,
    details: str,
    extra_lines: list[str] | None = None,
    details_label: str = "Details",
) -> list[str]:
    """Return a common status/details section."""
    lines = [title, f"Status: `{status}`", f"{details_label}: {details}"]
    if extra_lines:
        lines.extend(line for line in extra_lines if line)
    return lines
