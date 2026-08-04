"""Shared Home Assistant entity behavior and dynamic discovery helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PoolsideCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


class PoolsideEntity(CoordinatorEntity[PoolsideCoordinator]):
    """Base entity attached to one Poolside site."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str) -> None:
        """Initialize from coordinator-owned state."""
        super().__init__(coordinator)
        self.site_uuid = site_uuid

    @property
    def device_info(self) -> DeviceInfo:
        """Group every site-level entity under one Poolside hub device."""
        site = self.coordinator.site(self.site_uuid)
        return DeviceInfo(
            identifiers={(DOMAIN, site.uuid)},
            manufacturer="Poolside Tech",
            model="The Attendant",
            name=site.name,
        )

    async def async_write_control(self, control_uuid: str, changes: dict[str, object]) -> None:
        """Route entity writes through the coordinator safety boundary."""
        await self.coordinator.async_set_control(self.site_uuid, control_uuid, changes)

    async def async_activate_theme(self, theme_uuid: str) -> None:
        """Route Theme activation through the coordinator safety boundary."""
        await self.coordinator.async_activate_theme(self.site_uuid, theme_uuid)


def setup_dynamic_entities[EntityT: Entity](
    coordinator: PoolsideCoordinator,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[], Iterable[EntityT]],
    identity: Callable[[EntityT], str],
) -> Callable[[], None]:
    """Add newly discovered entities without duplicating existing registry entries."""
    known: set[str] = set()

    @callback
    def async_discover() -> None:
        entities: list[EntityT] = []
        for entity in factory():
            key = identity(entity)
            if key not in known:
                known.add(key)
                entities.append(entity)
        if entities:
            async_add_entities(entities)

    async_discover()
    return coordinator.async_add_listener(async_discover)


def scalar_states(values: Mapping[str, Any], *, boolean: bool) -> Iterable[tuple[str, Any]]:
    """Yield stable scalar states split by boolean platform."""
    for key, value in values.items():
        if isinstance(value, (dict, list, tuple)) or value is None:
            continue
        if isinstance(value, bool) is boolean:
            yield key, value
