"""Native Home Assistant fans for safe variable-speed Poolside blowers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .models import Control

_MAX_PERCENTAGE = 100


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up variable-speed blowers as native HA Fan entities."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideBlowerFan]:
    """Build fans only for confirmed high-level variable-speed blowers."""
    for site in coordinator.data.sites.values():
        for control in site.all_controls.values():
            if control.available and control.is_blower and control.supports_percentage:
                yield PoolsideBlowerFan(coordinator, site.uuid, control.uuid)


class PoolsideBlowerFan(PoolsideEntity, FanEntity):
    """One safe Poolside blower with native on/off and percentage control."""

    _attr_supported_features = FanEntityFeature.SET_SPEED
    _attr_percentage_step = 1

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, control_uuid: str) -> None:
        """Initialize from a stable high-level Control UUID."""
        control = coordinator.site(site_uuid).all_controls[control_uuid]
        super().__init__(coordinator, site_uuid, control.water_body_uuid)
        self.control_uuid = control_uuid
        self._attr_unique_id = f"{control_uuid}_fan"
        self._attr_name = control.name

    @property
    def _control(self) -> Control | None:
        """Return the latest high-level Control, if it still exists."""
        return self.coordinator.site(self.site_uuid).all_controls.get(self.control_uuid)

    @property
    def available(self) -> bool:
        """Withdraw the fan if Poolside disables or reclassifies it."""
        control = self._control
        return bool(
            super().available
            and control is not None
            and control.available
            and control.is_blower
            and control.supports_percentage
        )

    @property
    def is_on(self) -> bool:
        """Return the confirmed high-level desired status."""
        return bool(
            self._control and str(self._control.desired.get("Status", "OFF")).upper() == "ON"
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose that activation participates in confirmed body flow."""
        return {**super().extra_state_attributes, "poolside_requires_flow": True}

    @property
    def percentage(self) -> int | None:
        """Return Poolside's native 0-100 PowerLevel."""
        value = self._control.desired.get("PowerLevel") if self._control else None
        return (
            int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        )

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **_kwargs: Any,
    ) -> None:
        """Turn on using the safe high-level Control endpoint."""
        del preset_mode
        changes: dict[str, object] = {"Status": "ON"}
        if percentage is not None:
            changes["PowerLevel"] = round(float(percentage))
        await self.async_write_control(self.control_uuid, changes)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off using the safe high-level Control endpoint."""
        await self.async_write_control(self.control_uuid, {"Status": "OFF"})

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the verified 0-100 PowerLevel field without raw equipment writes."""
        if not 0 <= percentage <= _MAX_PERCENTAGE:
            raise ValueError("Fan percentage must be between 0 and 100")
        await self.async_write_control(
            self.control_uuid,
            {"Status": "OFF"} if percentage == 0 else {"Status": "ON", "PowerLevel": percentage},
        )
