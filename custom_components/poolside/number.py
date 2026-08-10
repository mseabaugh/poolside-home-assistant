"""Safe high-level Poolside Control percentages."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .redact import fingerprint
from .switch import _safe_binary

_MAX_POWER_LEVEL = 100


def _configured_power_level(control: Any) -> float | None:
    """Return the server-selected percentage without using it as a capability."""
    for key in ("PowerLevel", "PowerLevelRunning", "PowerLevelIdle"):
        value = control.desired.get(key)
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except TypeError, ValueError:
            continue
        if 0 <= parsed <= _MAX_POWER_LEVEL:
            return parsed
    return None


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up dynamically discovered safe percentage Controls."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(
    coordinator: PoolsideCoordinator,
) -> Iterable[PoolsideControlNumber | PoolsideHeaterTemperature]:
    """Build percentages only for already allow-listed high-level feature Controls."""
    for site in coordinator.data.sites.values():
        for control in site.all_controls.values():
            if (
                not control.restricted
                and not control.installer_only
                and _safe_binary(control)
                and control.supports_percentage
                and not control.is_blower
            ):
                yield PoolsideControlNumber(coordinator, site.uuid, control.uuid)
        for control in site.heating_controls.values():
            if control.available and not control.supports_temperature_setpoint:
                yield PoolsideHeaterTemperature(coordinator, site.uuid, control.uuid)


class PoolsideControlNumber(PoolsideEntity, NumberEntity):
    """A high-level Control power/intensity percentage."""

    _attr_native_min_value = 0
    _attr_native_max_value = _MAX_POWER_LEVEL
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, control_uuid: str) -> None:
        """Initialize from a stable Control UUID."""
        control = coordinator.site(site_uuid).all_controls[control_uuid]
        super().__init__(coordinator, site_uuid, control.water_body_uuid)
        self.control_uuid = control_uuid
        self._attr_unique_id = f"{control_uuid}_power_level"
        self._attr_name = f"{control.name} power level"

    @property
    def native_value(self) -> float | None:
        """Return the current desired percentage."""
        control = self.coordinator.site(self.site_uuid).all_controls[self.control_uuid]
        return _configured_power_level(control)

    @property
    def available(self) -> bool:
        """Keep passive setpoints available without enabling the Control itself."""
        control = self.coordinator.site(self.site_uuid).all_controls.get(self.control_uuid)
        return bool(
            self.coordinator.last_update_success
            and control is not None
            and not control.restricted
            and not control.installer_only
            and _safe_binary(control)
            and control.supports_percentage
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Associate route member percentages without leaking controller IDs."""
        route = self.coordinator.site(self.site_uuid).route_group_for_control(self.control_uuid)
        if route is None:
            return {}
        return {
            "poolside_route_group": fingerprint(route.key)[:12],
            "poolside_route_member": True,
        }

    async def async_set_native_value(self, value: float) -> None:
        """Write an integral Poolside percentage after Home Assistant range validation."""
        if not 0 <= value <= _MAX_POWER_LEVEL:
            raise ValueError("Power level must be between 0 and 100")
        await self.async_write_control(self.control_uuid, {"PowerLevel": round(value)})


class PoolsideHeaterTemperature(PoolsideEntity, NumberEntity):
    """Poolside pool/spa heater setpoint shown as a temperature control."""

    _attr_native_min_value = 32
    _attr_native_max_value = 110
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "°F"

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, control_uuid: str) -> None:
        """Initialize from a discovered Heating Control."""
        control = coordinator.site(site_uuid).all_controls[control_uuid]
        super().__init__(coordinator, site_uuid, control.water_body_uuid)
        self.control_uuid = control_uuid
        body = control.water_body_uuid
        site = coordinator.site(site_uuid)
        label = (
            site.bodies_of_water[body].name
            if body is not None and body in site.bodies_of_water
            else "Heater"
        )
        self._attr_unique_id = f"{control_uuid}_temperature"
        self._attr_name = f"{label} Heater"

    @property
    def native_value(self) -> float | None:
        """Return the current discovered heater setpoint."""
        control = self.coordinator.site(self.site_uuid).all_controls[self.control_uuid]
        value = control.desired.get("SetPoint")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @property
    def available(self) -> bool:
        """Hide a stale heater setpoint when its high-level Control is disabled."""
        control = self.coordinator.site(self.site_uuid).all_controls.get(self.control_uuid)
        return bool(
            super().available and control is not None and control.available and control.is_heating
        )

    async def async_set_native_value(self, value: float) -> None:
        """Write only the confirmed heater SetPoint field."""
        if not self._attr_native_min_value <= value <= self._attr_native_max_value:
            raise ValueError("Temperature must be between 32 and 110°F")
        await self.async_write_control(self.control_uuid, {"SetPoint": round(value)})
