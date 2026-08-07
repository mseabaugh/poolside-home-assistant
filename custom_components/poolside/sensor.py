"""Read-only Poolside equipment state sensors."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, scalar_states, setup_dynamic_entities


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up and dynamically extend equipment sensors."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideSensor]:
    """Build scalar non-boolean sensors from the latest snapshot."""
    for site in coordinator.data.sites.values():
        for equipment in site.equipment.values():
            for key, _value in scalar_states(equipment.states, boolean=False):
                if not _telemetry_is_applicable(equipment.type, key):
                    continue
                yield PoolsideSensor(coordinator, site.uuid, equipment.uuid, key)


def _telemetry_is_applicable(device_type: str, state_key: str) -> bool:
    """Drop generic physical fields that cannot apply to light-only devices."""
    lowered_type = device_type.casefold()
    lowered_key = state_key.casefold()
    if any(token in lowered_type for token in ("light", "strip", "led")):
        return lowered_key not in {"moving", "winterized", "rpm"}
    return True


class PoolsideSensor(PoolsideEntity, SensorEntity):
    """One discovered scalar equipment telemetry value."""

    def __init__(
        self,
        coordinator: PoolsideCoordinator,
        site_uuid: str,
        equipment_uuid: str,
        state_key: str,
    ) -> None:
        """Initialize a sensor from stable remote keys."""
        super().__init__(coordinator, site_uuid)
        self.equipment_uuid = equipment_uuid
        self.state_key = state_key
        equipment = coordinator.site(site_uuid).equipment[equipment_uuid]
        self._attr_unique_id = f"{equipment_uuid}_{state_key}"
        self._attr_name = f"{equipment.name} {state_key}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if state_key.casefold() == "rpm":
            self._attr_native_unit_of_measurement = "rpm"

    @property
    def native_value(self) -> Any:
        """Return the latest telemetry value."""
        equipment = self.coordinator.site(self.site_uuid).equipment.get(self.equipment_uuid)
        return None if equipment is None else equipment.states.get(self.state_key)

    @property
    def available(self) -> bool:
        """Require coordinator success and the discovered state key."""
        equipment = self.coordinator.site(self.site_uuid).equipment.get(self.equipment_uuid)
        return bool(
            super().available and equipment is not None and self.state_key in equipment.states
        )
