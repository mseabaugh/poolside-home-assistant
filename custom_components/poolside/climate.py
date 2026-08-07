"""Native Home Assistant climate entities for safe Poolside heaters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .models import Control

_MIN_TEMPERATURE = 32
_MAX_TEMPERATURE = 110


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up only heaters with a confirmed writable temperature setpoint."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideHeaterClimate]:
    """Build climate entities for confirmed high-level Heating Controls only."""
    for site in coordinator.data.sites.values():
        for control in site.heating_controls.values():
            if control.available and control.supports_temperature_setpoint:
                yield PoolsideHeaterClimate(coordinator, site.uuid, control.uuid)


class PoolsideHeaterClimate(PoolsideEntity, ClimateEntity):
    """A safe Poolside heater represented as one native thermostat control."""

    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = _MIN_TEMPERATURE
    _attr_max_temp = _MAX_TEMPERATURE
    _attr_target_temperature_step = 1
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, control_uuid: str) -> None:
        """Initialize from a stable high-level Heating Control UUID."""
        control = coordinator.site(site_uuid).all_controls[control_uuid]
        super().__init__(coordinator, site_uuid, control.water_body_uuid)
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self.control_uuid = control_uuid
        self._attr_unique_id = f"{control_uuid}_climate"
        self._attr_name = control.name

    @property
    def _control(self) -> Control | None:
        """Return the latest heating Control, if it remains discoverable."""
        return self.coordinator.site(self.site_uuid).all_controls.get(self.control_uuid)

    @property
    def available(self) -> bool:
        """Withdraw the thermostat if Poolside disables the heater."""
        control = self._control
        return bool(
            super().available
            and control is not None
            and control.available
            and control.supports_temperature_setpoint
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return only the confirmed high-level heating status."""
        return (
            HVACMode.HEAT
            if self._control and str(self._control.desired.get("Status", "OFF")).upper() == "ON"
            else HVACMode.OFF
        )

    @property
    def target_temperature(self) -> float | None:
        """Return the reported safe heater setpoint."""
        value = self._control.desired.get("SetPoint") if self._control else None
        try:
            return float(value) if value is not None and not isinstance(value, bool) else None
        except TypeError, ValueError:
            return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Write only the high-level heater status."""
        if hvac_mode not in self._attr_hvac_modes:
            raise ValueError("Only Off and Heat are supported")
        await self.async_write_control(
            self.control_uuid, {"Status": "ON" if hvac_mode == HVACMode.HEAT else "OFF"}
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Write only Poolside's confirmed SetPoint field."""
        value = kwargs.get(ATTR_TEMPERATURE)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not _MIN_TEMPERATURE <= value <= _MAX_TEMPERATURE
        ):
            raise ValueError("Temperature must be between 32 and 110°F")
        await self.async_write_control(self.control_uuid, {"SetPoint": round(value)})
