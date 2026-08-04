"""Read-only projection of Poolside schedules into Home Assistant calendars."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .schedule import schedule_events


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up one read-only schedule calendar per discovered site."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideCalendar]:
    """Build calendars only where a schedule document is present."""
    for site in coordinator.data.sites.values():
        if site.schedule_document:
            yield PoolsideCalendar(coordinator, site.uuid)


class PoolsideCalendar(PoolsideEntity, CalendarEntity):
    """Read-only weekly occurrences for one Poolside site."""

    _attr_name = "Schedule"

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str) -> None:
        """Initialize from a stable site UUID."""
        super().__init__(coordinator, site_uuid)
        self._attr_unique_id = f"{site_uuid}_schedule"

    @property
    def _timezone(self) -> ZoneInfo:
        """Prefer Poolside site timezone and safely fall back to Home Assistant."""
        site = self.coordinator.site(self.site_uuid)
        value = site.raw.get("TimeZone", self.coordinator.hass.config.time_zone)
        try:
            return ZoneInfo(str(value))
        except ZoneInfoNotFoundError:
            return ZoneInfo(self.coordinator.hass.config.time_zone)

    @property
    def _names(self) -> dict[str, str]:
        """Map schedule item identifiers to current friendly Control names."""
        site = self.coordinator.site(self.site_uuid)
        return {item.uuid: item.name for item in site.all_controls.values()}

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Convert domain occurrences into Home Assistant calendar events."""
        site = self.coordinator.site(self.site_uuid)
        return [
            CalendarEvent(summary=item.summary, start=item.start, end=item.end)
            for item in schedule_events(
                site.schedule_document,
                start,
                end,
                self._timezone,
                self._names,
            )
        ]

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next occurrence."""
        now = dt_util.now()
        events = self._events(now, now + timedelta(days=8))
        return events[0] if events else None

    async def async_get_events(
        self,
        _hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return occurrences in the requested range."""
        return self._events(start_date, end_date)
