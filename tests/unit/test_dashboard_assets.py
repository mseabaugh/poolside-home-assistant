"""Behavioral contracts for the bundled Lovelace dashboard asset."""

from __future__ import annotations

from pathlib import Path


def test_dashboard_assets_support_responsive_full_width_sections() -> None:
    """Bundled cards and the native template fill HA's responsive sections grid."""
    root = Path(__file__).parents[2]
    selector = (root / "custom_components/poolside/www/poolside-body-selector.js").read_text()
    dashboard = (root / "custom_components/poolside/www/poolside-dashboard.js").read_text()
    native = (root / "docs/native-dashboard.yaml").read_text()

    assert "getGridOptions()" in selector
    assert "columns: 12" in selector
    assert "getGridOptions()" in dashboard
    assert "columns: 12" in dashboard
    assert "type: sections" in native
    assert "max_columns: 3" in native
    assert "column_span: 3" in native
    assert "columns: full" in native
    assert "type: custom:poolside-heater-gauge" in native
    assert "max: 104" in native


def test_heater_gauge_keeps_mode_control_visible_and_supports_color_ranges() -> None:
    """The compact heater gauge exposes safe Climate controls and five bands."""
    root = Path(__file__).parents[2]
    gauge = (root / "custom_components/poolside/www/poolside-heater-gauge.js").read_text()
    native = (root / "docs/native-dashboard.yaml").read_text()

    assert "class PoolsideHeaterGauge" in gauge
    assert 'class="toggle"' in gauge
    assert 'callService("climate", "set_hvac_mode"' in gauge
    assert 'callService("climate", "set_temperature"' in gauge
    assert "ranges.length < 2 || ranges.length > 5" in gauge
    assert native.count("color:") == 6  # five heater bands plus water tile


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


def test_dashboard_bundles_and_uses_flat_poolside_icons() -> None:
    """Body and feature controls use only the current bundled flat icon set."""
    root = Path(__file__).parents[2]
    dashboard = (root / "custom_components/poolside/www/poolside-dashboard.js").read_text(
        encoding="utf-8"
    )
    icons = root / "custom_components" / "poolside" / "www" / "icons"

    assert {path.name for path in icons.iterdir()} == {
        "bubbler.png",
        "deck_jet.png",
        "fountain.png",
        "pool.png",
        "spa.png",
        "waterfall.png",
    }
    assert "_bodyIconPath(value)" in dashboard
    assert "_waterFeatureIconPath(state)" in dashboard
    assert "/poolside/icons/spa.png" in dashboard
    assert "/poolside/icons/pool.png" in dashboard
    assert "/poolside/icons/bubbler.png" in dashboard
    assert "/poolside/icons/deck_jet.png" in dashboard
    assert "/poolside/icons/fountain.png" in dashboard
    assert "/poolside/icons/waterfall.png" in dashboard


def test_dashboard_resolves_body_selector_from_protocol_attributes() -> None:
    """A stale configured entity ID falls back without matching entity names."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    resolver = dashboard.split("_resolveModeEntity() {", 1)[1].split("\n  }", 1)[0]
    assert "this.config.mode_entity" in resolver
    assert '"confirmed_water_flow"' in resolver
    assert '"poolside_body_ids"' in resolver
    assert "configured && isBodySelector" in resolver
    assert 'options.includes("Off")' in resolver
    assert 'id.includes("active_body")' not in resolver


def test_dashboard_classifies_controls_by_body_ids_only() -> None:
    """Ambiguous control names cannot move an entity to the wrong body."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    discovery = dashboard.split("_discoverEntities(mode) {", 1)[1].split(
        "\n  _discoverHomeData()", 1
    )[0]
    assert "poolside_body_ids" in discovery
    assert "poolside_body_id" in discovery
    assert "scope === poolBodyId" in discovery
    assert "scope === spaBodyId" in discovery
    assert 'identity.includes("pool")' not in discovery
    assert 'identity.includes("spa")' not in discovery


def test_dashboard_classifies_poolside_heat_controls_as_heating() -> None:
    """Poolside's `Heat` label must render in the native heater panel."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    groups = dashboard.split("_groups(ids) {", 1)[1].split("\n  _discoverEntities(mode)", 1)[0]
    assert r"\bheat(?:er|ing)?\b" in groups


def test_dashboard_confirms_cross_body_activation_before_native_service() -> None:
    """Inactive-body controls remain native but require an explicit flow confirmation."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "_confirmFlowForEntity(entityId)" in dashboard
    assert "poolside_requires_flow" in dashboard
    assert "window.confirm(message)" in dashboard
    assert '"poolside", "confirm_flow_switch"' in dashboard
    assert "button.checked = false" in dashboard


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
    assert "const chemistryPanel = chemistry.length ?" in dashboard
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


def test_dashboard_supports_native_fan_climate_and_combined_temperature_view() -> None:
    """The bundled compatibility card follows the native entity model."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "poolside-dashboard requires mode_entity" in dashboard
    assert '"fan", "climate"' in dashboard
    assert "fan-percentage" in dashboard
    assert "mdi:thermometer-water" in dashboard
    assert "native-light-slider" in dashboard
    assert "<ha-slider" in dashboard
    assert "heater-temperature-stepper" in dashboard
    assert "const heaterSwitch" in dashboard
    assert "const temperatureEntity = climate || setpoint" in dashboard
    assert "_temperatureColor(value)" in dashboard
    assert "((Number(value) || 32) - 32) / 72" in dashboard
    assert "--heater-temp-color" in dashboard
    assert '"set_temperature"' in dashboard
    assert "temperature-with-air" in dashboard
    assert "\\nAir ${this._stateValue(air)}" in dashboard
    assert "/pump.*rpm/" in dashboard
    assert 'stats.push(["mdi:pump", label, status])' in dashboard
    assert 'replace(/\\s+RPM$/i, "")' in dashboard
    assert "Water temperature, air temperature, pH, ORP, and chlorine (normalized)" in dashboard


def test_dashboard_uses_home_assistant_native_control_elements() -> None:
    """Every ordinary writable control uses HA's native switch, slider, or field."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "<ha-switch" in dashboard
    assert "<ha-slider" in dashboard
    assert "<ha-textfield" in dashboard
    assert "ha-switch.toggle[data-entity]" in dashboard
    assert "ha-switch.all-lights-toggle" in dashboard


def test_dashboard_keeps_body_selection_presentation_only_and_pairs_routes() -> None:
    """Only the confirmed Off action requests a flow-control shutdown batch."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert 'option.toLowerCase() === "off"' in dashboard
    assert "Turn off active water-flow Controls" in dashboard
    assert "_routeFeatureCard(states)" in dashboard
    assert "poolside_route_group" in dashboard
    assert "poolside_control_kind" in dashboard
    assert "route-select" in dashboard
    assert 'callService("select", "select_option"' in dashboard


def test_body_selector_shows_confirmed_flow_and_confirms_only_safe_off() -> None:
    """The selector cannot represent a local Pool/Spa valve or pump transition."""
    selector = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-body-selector.js"
    ).read_text(encoding="utf-8")

    assert "confirmed_water_flow" in selector
    assert 'option.toLowerCase() === "off"' in selector
    assert "Turn off active water-flow Controls" in selector
    assert "Pool and Spa select the dashboard view" in selector
    assert "button.textContent = option" in selector
    assert "pointer-events: none" in selector
    assert "this._fill.style.left" in selector
    assert "this.shadowRoot || this.attachShadow" in selector
    assert "Switch from ${current}" not in selector


def test_dashboard_uses_a_normalized_line_trend_on_the_homeowner_view() -> None:
    """Mixed-unit controller measurements render as a line trend, not state bars."""
    dashboard = (
        Path(__file__).parents[2]
        / "custom_components"
        / "poolside"
        / "www"
        / "poolside-dashboard.js"
    ).read_text(encoding="utf-8")

    assert 'data-history="overview"' in dashboard
    assert "Water and chemistry — 24 hours" in dashboard
    assert "<polyline" in dashboard
    assert (
        "[...this._temperatureStates(), ...this._ambientTemperatureStates(), ...chemistry]"
        in dashboard
    )
    assert "schedule_entities" in dashboard
    assert "this.shadowRoot || this.attachShadow" in dashboard
