"""Read-only Poolside boolean equipment state sensors."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, scalar_states, setup_dynamic_entities


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up and dynamically extend boolean equipment sensors."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideBinarySensor]:
    """Build boolean sensors from the latest snapshot."""
    for site in coordinator.data.sites.values():
        for equipment in site.equipment.values():
            for key, _value in scalar_states(equipment.states, boolean=True):
                yield PoolsideBinarySensor(coordinator, site.uuid, equipment.uuid, key)


class PoolsideBinarySensor(PoolsideEntity, BinarySensorEntity):
    """One discovered boolean equipment telemetry value."""

    def __init__(
        self,
        coordinator: PoolsideCoordinator,
        site_uuid: str,
        equipment_uuid: str,
        state_key: str,
    ) -> None:
        """Initialize from stable remote keys."""
        super().__init__(coordinator, site_uuid)
        self.equipment_uuid = equipment_uuid
        self.state_key = state_key
        equipment = coordinator.site(site_uuid).equipment[equipment_uuid]
        self._attr_unique_id = f"{equipment_uuid}_{state_key}"
        self._attr_name = f"{equipment.name} {state_key}"

    @property
    def is_on(self) -> bool | None:
        """Return the latest boolean telemetry value."""
        equipment = self.coordinator.site(self.site_uuid).equipment.get(self.equipment_uuid)
        if equipment is None:
            return None
        value = equipment.states.get(self.state_key)
        return value if isinstance(value, bool) else None

    @property
    def available(self) -> bool:
        """Require coordinator success and a boolean state."""
        return bool(super().available and self.is_on is not None)
