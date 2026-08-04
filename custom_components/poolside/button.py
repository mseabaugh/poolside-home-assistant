"""Stateless Poolside Theme activation buttons."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up dynamically discovered Theme buttons."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideThemeButton]:
    """Build one button for each discovered Theme."""
    for site in coordinator.data.sites.values():
        for theme in site.themes.values():
            yield PoolsideThemeButton(coordinator, site.uuid, theme.uuid)


class PoolsideThemeButton(PoolsideEntity, ButtonEntity):
    """Activate one discovered Theme."""

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, theme_uuid: str) -> None:
        """Initialize from a stable Theme UUID."""
        super().__init__(coordinator, site_uuid)
        self.theme_uuid = theme_uuid
        theme = coordinator.site(site_uuid).themes[theme_uuid]
        self._attr_unique_id = f"{theme_uuid}_activate"
        self._attr_name = theme.name

    async def async_press(self) -> None:
        """Activate using the confirmed `Status=ON` operation."""
        await self.async_activate_theme(self.theme_uuid)
