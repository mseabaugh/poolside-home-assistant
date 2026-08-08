"""Unit tests for entity edge behavior at the Home Assistant boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.poolside.binary_sensor import PoolsideBinarySensor
from custom_components.poolside.binary_sensor import _entities as binary_entities
from custom_components.poolside.calendar import PoolsideCalendar
from custom_components.poolside.calendar import _entities as calendar_entities
from custom_components.poolside.climate import PoolsideHeaterClimate
from custom_components.poolside.climate import _entities as climate_entities
from custom_components.poolside.coordinator import PoolsideCoordinator
from custom_components.poolside.entity import scalar_states, setup_dynamic_entities
from custom_components.poolside.fan import PoolsideBlowerFan
from custom_components.poolside.fan import _entities as fan_entities
from custom_components.poolside.light import PoolsideLight
from custom_components.poolside.models import (
    BodyOfWater,
    Equipment,
    PoolsideData,
    Site,
    Theme,
    apply_runtime,
    discover_sites,
)
from custom_components.poolside.number import PoolsideControlNumber, PoolsideHeaterTemperature
from custom_components.poolside.number import _entities as number_entities
from custom_components.poolside.select import (
    PoolsideActiveBodySelect,
    PoolsideThemeSelect,
    _theme_options,
)
from custom_components.poolside.select import _entities as select_entities
from custom_components.poolside.sensor import _entities as sensor_entities
from custom_components.poolside.sensor import _telemetry_is_applicable
from custom_components.poolside.switch import PoolsideSwitch

pytestmark = pytest.mark.unit


class StubCoordinator(PoolsideCoordinator):
    """Small coordinator double for deterministic entity property tests."""

    def __init__(self, site: Site) -> None:
        self.data = PoolsideData({site.uuid: site})
        self.last_update_success = True
        self.hass = cast("HomeAssistant", SimpleNamespace(config=SimpleNamespace(time_zone="UTC")))
        self.control_writes: list[tuple[str, str, dict[str, object]]] = []
        self.theme_writes: list[tuple[str, str]] = []
        self._active_bodies: dict[tuple[str, str], str | None] = {}
        self._flow_transitions: dict[tuple[str, str], dict[str, object]] = {}
        self.listener: Any = None

    def site(self, site_uuid: str) -> Site:
        return self.data.sites[site_uuid]

    async def async_set_control(
        self, site_uuid: str, control_uuid: str, changes: dict[str, object]
    ) -> None:
        self.control_writes.append((site_uuid, control_uuid, changes))

    async def async_activate_theme(self, site_uuid: str, theme_uuid: str) -> None:
        self.theme_writes.append((site_uuid, theme_uuid))

    async def async_run_flow_switch(
        self, site_uuid: str, group_key: str, body_uuid: str | None
    ) -> None:
        """Model a confirmed procedure without issuing equipment writes."""
        self.set_active_body(site_uuid, body_uuid, group_key)

    def async_add_listener(
        self, listener: Callable[[], None], _context: Any = None
    ) -> Callable[[], None]:
        self.listener = listener
        return lambda: None


def _coordinator(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> StubCoordinator:
    site = discover_sites(user_config).sites["site-alpha"]
    return StubCoordinator(apply_runtime(site, states_payload, desired_payload))


def test_scalar_state_filter_and_dynamic_entity_deduplication(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Complex values are ignored and repeated discoveries do not duplicate entities."""
    assert list(scalar_states({"nested": {}, "none": None, "value": 2}, boolean=False)) == [
        ("value", 2)
    ]
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    entity = PoolsideLight(coordinator, "site-alpha", "light-one")
    added: list[PoolsideLight] = []

    def add_entities(
        entities: Iterable[Entity],
        _update_before_add: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        added.extend(cast("Iterable[PoolsideLight]", entities))

    remove = setup_dynamic_entities(
        coordinator,
        cast("AddEntitiesCallback", add_entities),
        lambda: [entity, entity],
        lambda item: str(item.unique_id),
    )
    assert added == [entity]
    coordinator.listener()
    assert added == [entity]
    remove()


def test_binary_sensor_handles_disappearing_equipment(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """A removed device makes its old registry entity unavailable instead of raising."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    entity = PoolsideBinarySensor(coordinator, "site-alpha", "pump-one", "Online")
    site = coordinator.site("site-alpha")
    coordinator.data = PoolsideData({site.uuid: replace(site, equipment={})})
    assert entity.is_on is None
    assert not entity.available


def test_light_telemetry_filters_non_applicable_runtime_fields(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Light-only runtime fields do not become misleading diagnostics."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    site = coordinator.site("site-alpha")
    strip = Equipment(
        "strip-one",
        "Strip 1",
        "Light Strip",
        site.uuid,
        {"Moving": False, "Winterized": False, "Online": True, "Brightness": 90, "RPM": 1},
    )
    coordinator.data = PoolsideData({site.uuid: replace(site, equipment={strip.uuid: strip})})

    assert [entity.state_key for entity in binary_entities(coordinator)] == ["Online"]
    assert [entity.state_key for entity in sensor_entities(coordinator)] == ["Brightness"]


async def test_calendar_fallback_empty_event_and_api(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Invalid remote zones fall back locally and an empty schedule stays read-only."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    site = coordinator.site("site-alpha")
    empty = replace(
        site,
        raw={**site.raw, "TimeZone": "Not/A_Zone"},
        schedule_document={"Schedule": []},
    )
    coordinator.data = PoolsideData({site.uuid: empty})
    calendar = PoolsideCalendar(coordinator, site.uuid)
    assert calendar._timezone == ZoneInfo("UTC")
    assert calendar.event is None
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert await calendar.async_get_events(coordinator.hass, start, start) == []
    coordinator.data = PoolsideData({site.uuid: replace(empty, schedule_document={})})
    assert list(calendar_entities(coordinator)) == []


async def test_light_edge_states_and_effect_validation(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Malformed light state is unavailable and only discovered effects may be written."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    site = coordinator.site("site-alpha")
    original = site.controls["light-one"]
    no_effects = replace(
        original,
        raw={"UUID": original.uuid, "Type": "Pool Light"},
        desired={"Brightness": True, "LightName": 10},
    )
    coordinator.data = PoolsideData(
        {site.uuid: replace(site, controls={**site.controls, original.uuid: no_effects})}
    )
    light = PoolsideLight(coordinator, site.uuid, original.uuid)
    assert light.brightness is None
    assert light.effect is None
    assert light.effect_list == []
    await light.async_turn_on()
    await light.async_turn_off()

    invalid_brightness = replace(no_effects, desired={"Brightness": 101})
    current = coordinator.site(site.uuid)
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                current, controls={**current.controls, original.uuid: invalid_brightness}
            )
        }
    )
    assert light.brightness is None

    coordinator.data = PoolsideData({site.uuid: site})
    light = PoolsideLight(coordinator, site.uuid, original.uuid)
    await light.async_turn_on(effect="Blue")
    with pytest.raises(ValueError, match="not available"):
        await light.async_turn_on(effect="Unknown")
    assert coordinator.control_writes[-1][2]["LightName"] == "Blue"


async def test_number_and_theme_failure_paths(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Numbers reject invalid ranges and duplicate Theme names remain selectable."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    site = coordinator.site("site-alpha")
    control = site.controls["filter-one"]
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                site,
                controls={
                    **site.controls,
                    control.uuid: replace(control, desired={"PowerLevel": True}),
                },
            )
        }
    )
    number = PoolsideControlNumber(coordinator, site.uuid, control.uuid)
    assert number.native_value is None
    with pytest.raises(ValueError, match="between"):
        await number.async_set_native_value(101)

    themes = {
        "theme-a": Theme("theme-a", "Party", site.uuid, {"isWorking": False}),
        "theme-b": Theme("theme-b", "Party", site.uuid, {"isWorking": True}),
    }
    current = coordinator.site(site.uuid)
    coordinator.data = PoolsideData({site.uuid: replace(current, themes=themes)})
    assert _theme_options(coordinator, site.uuid) == {
        "Party (1)": "theme-a",
        "Party (2)": "theme-b",
    }
    select = PoolsideThemeSelect(coordinator, site.uuid)
    assert select.current_option == "Party (2)"
    await select.async_select_option("Party (1)")
    with pytest.raises(ValueError, match="not available"):
        await select.async_select_option("Missing")

    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                current,
                themes={key: replace(theme, raw={}) for key, theme in themes.items()},
            )
        }
    )
    inactive = PoolsideThemeSelect(coordinator, site.uuid)
    assert inactive.current_option is None
    coordinator.data = PoolsideData({site.uuid: replace(current, themes={})})
    assert list(select_entities(coordinator)) == []


async def test_heater_temperature_entity_reads_and_writes_setpoint(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Heating controls are temperature numbers and preserve SetPoint semantics."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    heater = PoolsideHeaterTemperature(coordinator, "site-alpha", "heat-one")
    assert heater.native_value == 82
    await heater.async_set_native_value(85)
    assert coordinator.control_writes[-1] == ("site-alpha", "heat-one", {"SetPoint": 85})
    with pytest.raises(ValueError, match="between"):
        await heater.async_set_native_value(111)
    current = coordinator.site("site-alpha")
    control = current.controls["heat-one"]
    coordinator.data = PoolsideData(
        {
            current.uuid: replace(
                current,
                controls={
                    **current.controls,
                    "heat-one": replace(control, desired={"SetPoint": "bad"}),
                },
            )
        }
    )
    dynamic_heater: Any = heater
    assert dynamic_heater.native_value is None
    coordinator.data = PoolsideData(
        {
            current.uuid: replace(
                current, controls={**current.controls, "heat-one": replace(control, desired={})}
            )
        }
    )
    if dynamic_heater.native_value is not None:
        raise AssertionError("malformed setpoint should be unavailable")

    body = BodyOfWater("spa-body", "Spa", "Spa", current.uuid)
    spa_control = replace(control, raw={"BodyOfWater": body.uuid, "Type": "HeatingControl"})
    coordinator.data = PoolsideData(
        {
            current.uuid: replace(
                current,
                bodies_of_water={body.uuid: body},
                controls={**current.controls, control.uuid: spa_control},
            )
        }
    )
    assert PoolsideHeaterTemperature(coordinator, current.uuid, control.uuid).name == "Spa Heater"


async def test_native_climate_and_fan_preserve_high_level_control_boundary(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Native HA controls use only confirmed Heater and Blower fields."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    site = coordinator.site("site-alpha")
    blower = replace(
        site.controls["filter-one"],
        uuid="blower-one",
        name="Spa Blower",
        type="Blower",
        desired={"Status": "ON", "PowerLevel": 65},
    )
    coordinator.data = PoolsideData(
        {site.uuid: replace(site, controls={**site.controls, blower.uuid: blower})}
    )
    climate = PoolsideHeaterClimate(coordinator, site.uuid, "heat-one")
    fan = PoolsideBlowerFan(coordinator, site.uuid, blower.uuid)

    assert climate.target_temperature == 82
    assert climate.hvac_mode.value == "heat"
    assert climate.available
    assert fan.is_on
    assert fan.percentage == 65
    assert fan.available
    assert [entity.control_uuid for entity in climate_entities(coordinator)] == ["heat-one"]
    assert [entity.control_uuid for entity in fan_entities(coordinator)] == [blower.uuid]
    await climate.async_set_hvac_mode(HVACMode.OFF)
    await climate.async_set_temperature(temperature=86)
    with pytest.raises(ValueError, match="Only Off"):
        await climate.async_set_hvac_mode(HVACMode.COOL)
    with pytest.raises(ValueError, match="between"):
        await climate.async_set_temperature(temperature=True)
    await fan.async_turn_on()
    await fan.async_turn_on(percentage=72)
    await fan.async_turn_off()
    await fan.async_set_percentage(0)
    with pytest.raises(ValueError, match="between"):
        await fan.async_set_percentage(101)
    assert coordinator.control_writes[-6:] == [
        (site.uuid, "heat-one", {"Status": "OFF"}),
        (site.uuid, "heat-one", {"SetPoint": 86}),
        (site.uuid, blower.uuid, {"Status": "ON"}),
        (site.uuid, blower.uuid, {"Status": "ON", "PowerLevel": 72}),
        (site.uuid, blower.uuid, {"Status": "OFF"}),
        (site.uuid, blower.uuid, {"Status": "OFF"}),
    ]
    malformed = replace(
        site.controls["heat-one"], desired={"Status": "OFF", "SetPoint": "bad", "Restricted": True}
    )
    unavailable_blower = replace(blower, desired={"PowerLevel": True, "Restricted": True})
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                site,
                controls={
                    **site.controls,
                    malformed.uuid: malformed,
                    blower.uuid: unavailable_blower,
                },
            )
        }
    )
    assert str(climate.target_temperature) == "None"
    assert list(fan_entities(coordinator)) == []
    assert list(climate_entities(coordinator)) == []
    legacy_heater = replace(site.controls["heat-one"], desired={})
    coordinator.data = PoolsideData(
        {site.uuid: replace(site, controls={**site.controls, legacy_heater.uuid: legacy_heater})}
    )
    assert any(entity.control_uuid == legacy_heater.uuid for entity in number_entities(coordinator))


async def test_active_body_scope_exposes_options_and_filters_controls(  # noqa: PLR0915
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """The local body selector scopes controls without issuing a remote write."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    site = coordinator.site("site-alpha")
    pool = BodyOfWater("pool", "Pool", "Pool", site.uuid)
    spa = BodyOfWater(
        "spa",
        "Spa",
        "Spa",
        site.uuid,
        {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}},
    )
    pool_light = replace(site.controls["light-one"], raw={"BodyOfWater": "pool", "Type": "Light"})
    spa_control = replace(site.controls["filter-one"], raw={"BodyOfWater": "spa", "Type": "Filter"})
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                site,
                bodies_of_water={"pool": pool, "spa": spa},
                controls={"light-one": pool_light, "filter-one": spa_control},
            )
        }
    )
    coordinator.async_update_listeners = lambda: None  # type: ignore[method-assign]
    selector = PoolsideActiveBodySelect(coordinator, site.uuid)
    assert selector.options == ["Off", "Pool", "Spa"]
    assert selector.current_option == "Off"
    assert selector.device_info["model"] == "Body Group"
    assert selector.extra_state_attributes["flow_procedure_available"] is False
    assert selector.extra_state_attributes["flow_procedure_reason"] == (
        "Poolside has not reported flow-procedure metadata"
    )
    assert not selector.available
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                coordinator.site(site.uuid),
                bodies_of_water={
                    "pool": pool,
                    "spa": spa,
                    "spa-2": BodyOfWater("spa-2", "Spa", "Spa", site.uuid),
                },
            )
        }
    )
    assert selector.options == ["Off", "Pool", "Spa (1)"]
    disconnected = PoolsideActiveBodySelect(coordinator, site.uuid, frozenset({"spa-2"}))
    assert disconnected.options == ["Off", "Spa (1)"]
    assert disconnected.device_info["model"] == "Body of Water"
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                coordinator.site(site.uuid),
                bodies_of_water={"pool": pool, "spa": spa},
                flow_procedure={"FlowBasedProcedures": [], "ControlBasedProcedures": []},
            )
        }
    )
    light = PoolsideLight(coordinator, site.uuid, "light-one")
    switch = PoolsideSwitch(coordinator, site.uuid, "filter-one")
    assert light.available
    assert switch.available
    assert light.device_info["name"] == "Pool"
    assert light.device_info["via_device"] == ("poolside", "site-alpha")
    assert switch.device_info["name"] == "Spa"
    await selector.async_select_option("Pool")
    coordinator.set_active_body(site.uuid, "pool")
    assert coordinator.active_body(site.uuid) == "pool"
    assert selector.current_option == "Pool"
    await selector.async_select_option("Pool")
    coordinator._flow_transitions[(site.uuid, "pool|spa")] = {"state": "Moving valves"}
    assert selector.extra_state_attributes["transition_state"] == "Moving valves"
    coordinator._flow_transitions.clear()
    assert light.available
    assert not coordinator.body_is_visible(site.uuid, "spa")
    assert coordinator.body_is_visible(site.uuid, "pond")
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                coordinator.site(site.uuid),
                bodies_of_water={
                    "pond": BodyOfWater("pond", "Pond", "Pond", site.uuid),
                    "pool": pool,
                    "spa": spa,
                },
            )
        }
    )
    assert coordinator.body_is_visible(site.uuid, "pond")
    coordinator._active_bodies.clear()
    assert any(
        isinstance(entity, PoolsideActiveBodySelect) for entity in select_entities(coordinator)
    )
    with pytest.raises(ValueError, match="not available"):
        await selector.async_select_option("Unknown")
    coordinator._active_bodies[(site.uuid, "pool|spa")] = "missing"
    assert selector.current_option == "Off"
    assert coordinator.body_is_visible(site.uuid, "pond")
    with pytest.raises(ValueError, match="not available"):
        coordinator.set_active_body(site.uuid, "missing")
    with pytest.raises(ValueError, match="group is required"):
        coordinator.set_active_body(site.uuid, None)
    coordinator.last_update_success = False
    assert not light.available


async def test_switch_write_round_trip(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Binary feature controls remain writable through the safety façade."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    switch = PoolsideSwitch(coordinator, "site-alpha", "filter-one")
    await switch.async_turn_on()
    assert coordinator.control_writes[-1][2] == {"Status": "ON"}


def test_disabled_heater_is_hidden_from_number_entities(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Restricted heaters are retained in data but omitted from UI discovery."""
    coordinator = _coordinator(user_config, states_payload, desired_payload)
    site = coordinator.site("site-alpha")
    heater = site.controls["heat-one"]
    existing_heater = PoolsideHeaterTemperature(coordinator, site.uuid, heater.uuid)
    existing_filter = PoolsideSwitch(coordinator, site.uuid, "filter-one")
    coordinator.data = PoolsideData(
        {
            site.uuid: replace(
                site,
                controls={
                    **site.controls,
                    heater.uuid: replace(heater, desired={"Restricted": True}),
                    "filter-one": replace(
                        site.controls["filter-one"], desired={"Restricted": True}
                    ),
                },
            )
        }
    )
    assert all(entity.control_uuid != heater.uuid for entity in number_entities(coordinator))
    assert not existing_heater.available
    assert not existing_filter.available


def test_light_telemetry_filters_generic_physical_fields() -> None:
    """LED strips keep light state but drop impossible movement fields."""
    assert _telemetry_is_applicable("LightDriver", "ActualBrightness")
    assert _telemetry_is_applicable("LED Strip", "ActualSpeed")
    assert not _telemetry_is_applicable("LED Strip", "Moving")
    assert not _telemetry_is_applicable("LED Strip", "Winterized")
    assert not _telemetry_is_applicable("LED Strip", "RPM")
    assert not _telemetry_is_applicable("Pump", "Brightness")
    assert not _telemetry_is_applicable("Three Way Actuator", "RPM")
    assert _telemetry_is_applicable("Pump", "RPM")
