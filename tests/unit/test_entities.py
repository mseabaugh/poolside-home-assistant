"""Unit tests for entity edge behavior at the Home Assistant boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.poolside.binary_sensor import PoolsideBinarySensor
from custom_components.poolside.calendar import PoolsideCalendar
from custom_components.poolside.calendar import _entities as calendar_entities
from custom_components.poolside.coordinator import PoolsideCoordinator
from custom_components.poolside.entity import scalar_states, setup_dynamic_entities
from custom_components.poolside.light import PoolsideLight
from custom_components.poolside.models import (
    PoolsideData,
    Site,
    Theme,
    apply_runtime,
    discover_sites,
)
from custom_components.poolside.number import PoolsideControlNumber, PoolsideHeaterTemperature
from custom_components.poolside.select import PoolsideThemeSelect, _theme_options
from custom_components.poolside.select import _entities as select_entities

pytestmark = pytest.mark.unit


class StubCoordinator(PoolsideCoordinator):
    """Small coordinator double for deterministic entity property tests."""

    def __init__(self, site: Site) -> None:
        self.data = PoolsideData({site.uuid: site})
        self.last_update_success = True
        self.hass = cast("HomeAssistant", SimpleNamespace(config=SimpleNamespace(time_zone="UTC")))
        self.control_writes: list[tuple[str, str, dict[str, object]]] = []
        self.theme_writes: list[tuple[str, str]] = []
        self.listener: Any = None

    def site(self, site_uuid: str) -> Site:
        return self.data.sites[site_uuid]

    async def async_set_control(
        self, site_uuid: str, control_uuid: str, changes: dict[str, object]
    ) -> None:
        self.control_writes.append((site_uuid, control_uuid, changes))

    async def async_activate_theme(self, site_uuid: str, theme_uuid: str) -> None:
        self.theme_writes.append((site_uuid, theme_uuid))

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
    assert heater.native_value is None
    coordinator.data = PoolsideData(
        {
            current.uuid: replace(
                current, controls={**current.controls, "heat-one": replace(control, desired={})}
            )
        }
    )
    if heater.native_value is not None:
        raise AssertionError("malformed setpoint should be unavailable")
