"""Dashboard traversal shared by the monitoring tests."""

from collections.abc import Iterator


def iter_panels(dashboard: dict) -> Iterator[dict]:
    """Yield every panel, including those nested in a collapsed row."""
    for panel in dashboard["panels"]:
        yield panel
        yield from panel.get("panels", [])
