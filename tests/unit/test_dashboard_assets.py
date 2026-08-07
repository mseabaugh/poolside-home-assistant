"""Behavioral contracts for the bundled Lovelace dashboard asset."""

from __future__ import annotations

from pathlib import Path


def test_dashboard_discovers_water_telemetry_alongside_configured_sensors() -> None:
    """A manual diagnostic list must not hide the authoritative water sensor."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "configuredDiagnostics" in dashboard
    assert "new Set([...discovered.telemetry, ...configuredDiagnostics])" in dashboard
    assert "/water.*thermistor/" in dashboard
