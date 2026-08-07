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


def test_dashboard_prefers_live_equipment_readings_in_gauges() -> None:
    """Targets belong in diagnostics, while gauges show current physical data."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "winterized|fault|online|desired" in dashboard
    assert "primary.*pump.*drivetemperature" in dashboard
    assert "feature.*pump.*drivetemperature" in dashboard
    assert "this._telemetryLabel(state)" in dashboard


def test_dashboard_provides_a_safe_all_lights_group_control() -> None:
    """Only discovered light entities may be targeted by the group control."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "_allLightsControl(lightIds)" in dashboard
    assert "All lights" in dashboard
    assert "all-lights-preset" in dashboard
    assert 'id.startsWith("light.") && this._hass.states[id]' in dashboard
    assert 'callService("light", allOn ? "turn_off" : "turn_on"' in dashboard


def test_homeowner_dashboard_is_conditional_and_rounds_live_values() -> None:
    """The homeowner view must avoid empty sections and raw controller precision."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "Water chemistry" in dashboard
    assert "Schedules" in dashboard
    assert "Water features" in dashboard
    assert "_individualLights(lightIds)" in dashboard
    assert "_featureCards(ids)" in dashboard
    assert "temperature-cool" in dashboard
    assert "history/period/" in dashboard
    assert "toFixed(2)" in dashboard
    assert "if (chemistry.length)" in dashboard
    assert "if (schedules.length)" in dashboard
    assert 'return state && !this._unavailable(state) && state.state === "on"' in dashboard
    assert 'details class="more"' not in dashboard
    assert "Daily controls" not in dashboard


def test_dashboard_hides_unavailable_controls_and_keeps_power_levels_as_percentages() -> None:
    """A homeowner card must never surface disabled controls or raw power units."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "_isDisplayableControl(state)" in dashboard
    assert 'replace(/ power level$/i, "")' in dashboard
    assert 'const unit = /power level/i.test(this._controlLabel(state)) ? "%"' in dashboard
    assert "stroke-dasharray" in dashboard
