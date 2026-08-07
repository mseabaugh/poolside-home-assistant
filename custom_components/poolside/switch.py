"""Safe high-level binary Poolside Controls."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .models import Control

_SAFE_TYPE_HINTS: Final = (
    "blower",
    "cleaner",
    "filter",
    "heat",
    "heater",
    "jet",
    "spillover",
    "waterfeature",
    "water feature",
)


def _safe_binary(control: Control) -> bool:
    """Classify only confirmed high-level non-light feature Controls."""
    lowered = control.type.lower()
    return not control.is_light and any(hint in lowered for hint in _SAFE_TYPE_HINTS)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up dynamically discovered safe Control switches."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideSwitch]:
    """Build switches for allow-listed Control classifications."""
    for site in coordinator.data.sites.values():
        for control in site.all_controls.values():
            if (
                control.available
                and _safe_binary(control)
                and not (control.is_blower and control.supports_percentage)
                and not control.supports_temperature_setpoint
            ):
                yield PoolsideSwitch(coordinator, site.uuid, control.uuid)


class PoolsideSwitch(PoolsideEntity, SwitchEntity):
    """A safe discovered high-level binary Control."""

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, control_uuid: str) -> None:
        """Initialize from a stable Control UUID."""
        control = coordinator.site(site_uuid).all_controls[control_uuid]
        super().__init__(coordinator, site_uuid, control.water_body_uuid)
        self.control_uuid = control_uuid
        self._attr_unique_id = control_uuid
        self._attr_name = control.name

    @property
    def is_on(self) -> bool:
        """Return desired high-level Control status."""
        control = self.coordinator.site(self.site_uuid).all_controls[self.control_uuid]
        return str(control.desired.get("Status", "OFF")).upper() == "ON"

    @property
    def available(self) -> bool:
        """Hide an existing entity when Poolside no longer permits its control."""
        control = self.coordinator.site(self.site_uuid).all_controls.get(self.control_uuid)
        return bool(
            super().available
            and control is not None
            and control.available
            and _safe_binary(control)
        )

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on through the high-level Control API."""
        await self.async_write_control(self.control_uuid, {"Status": "ON"})

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off through the high-level Control API."""
        await self.async_write_control(self.control_uuid, {"Status": "OFF"})
