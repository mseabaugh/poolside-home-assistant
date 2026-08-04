"""Site-level Poolside Theme selector."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up one dynamically updated Theme selector per site."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideThemeSelect]:
    """Build a selector only for sites that have Themes."""
    for site in coordinator.data.sites.values():
        if site.themes:
            yield PoolsideThemeSelect(coordinator, site.uuid)


def _theme_options(coordinator: PoolsideCoordinator, site_uuid: str) -> dict[str, str]:
    """Create human-readable unique options without exposing remote identifiers."""
    themes = list(coordinator.site(site_uuid).themes.values())
    counts = Counter(theme.name for theme in themes)
    seen: Counter[str] = Counter()
    options: dict[str, str] = {}
    for theme in themes:
        seen[theme.name] += 1
        option = theme.name
        if counts[theme.name] > 1:
            option = f"{theme.name} ({seen[theme.name]})"
        options[option] = theme.uuid
    return options


class PoolsideThemeSelect(PoolsideEntity, SelectEntity):
    """Activate one of a site's discovered Themes."""

    _attr_name = "Theme"

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str) -> None:
        """Initialize from a stable site UUID."""
        super().__init__(coordinator, site_uuid)
        self._attr_unique_id = f"{site_uuid}_theme"

    @property
    def _options_map(self) -> dict[str, str]:
        """Return the latest option-to-Theme mapping."""
        return _theme_options(self.coordinator, self.site_uuid)

    @property
    def options(self) -> list[str]:
        """Return dynamically discovered Theme names."""
        return list(self._options_map)

    @property
    def current_option(self) -> str | None:
        """Return a Theme explicitly marked active, if supplied by Poolside."""
        themes = self.coordinator.site(self.site_uuid).themes
        for option, theme_uuid in self._options_map.items():
            if themes[theme_uuid].raw.get("isWorking") is True:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        """Activate the selected discovered Theme."""
        theme_uuid = self._options_map.get(option)
        if theme_uuid is None:
            raise ValueError("Theme option is not available")
        await self.async_activate_theme(theme_uuid)
