"""Read-only Poolside schedule projection and guarded mutation seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .exceptions import ScheduleMutationUnavailableError

_WEEKDAYS = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


@dataclass(frozen=True, slots=True)
class ScheduleEvent:
    """One projected schedule occurrence."""

    item_uuid: str
    summary: str
    start: datetime
    end: datetime
    status: str


def canonical_hash(document: Mapping[str, Any]) -> str:
    """Hash a JSON document deterministically for local stale-data comparisons."""
    serialized = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _parse_time(value: Any) -> time | None:
    """Parse confirmed 24-hour schedule time strings."""
    if not isinstance(value, str):
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _dates_for_weekday(start: date, end: date, weekday: int) -> list[date]:
    """Return matching dates in an inclusive date range."""
    first = start + timedelta(days=(weekday - start.weekday()) % 7)
    dates: list[date] = []
    current = first
    while current <= end:
        dates.append(current)
        current += timedelta(days=7)
    return dates


def schedule_events(  # noqa: C901, PLR0912
    document: Mapping[str, Any],
    start: datetime,
    end: datetime,
    timezone: ZoneInfo,
    item_names: Mapping[str, str] | None = None,
) -> list[ScheduleEvent]:
    """Project weekly schedule rows into Home Assistant calendar occurrences."""
    if end <= start:
        return []
    names = item_names or {}
    schedule = document.get("Schedule", [])
    if not isinstance(schedule, list):
        return []
    local_start = start.astimezone(timezone)
    local_end = end.astimezone(timezone)
    events: list[ScheduleEvent] = []
    for item in schedule:
        if not isinstance(item, Mapping):
            continue
        item_uuid = item.get("ItemUUID")
        elements = item.get("ScheduleElements", [])
        if not isinstance(item_uuid, str) or not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, Mapping):
                continue
            day = element.get("Day")
            weekday = _WEEKDAYS.get(day) if isinstance(day, str) else None
            times = element.get("Times", [])
            if weekday is None or not isinstance(times, list):
                continue
            for row in times:
                if not isinstance(row, Mapping):
                    continue
                start_time = _parse_time(row.get("StartTime"))
                end_time = _parse_time(row.get("EndTime"))
                if start_time is None or end_time is None:
                    continue
                for event_date in _dates_for_weekday(
                    local_start.date() - timedelta(days=1),
                    local_end.date() + timedelta(days=1),
                    weekday,
                ):
                    event_start = datetime.combine(event_date, start_time, timezone)
                    event_end = datetime.combine(event_date, end_time, timezone)
                    if event_end <= event_start:
                        event_end += timedelta(days=1)
                    if event_end <= local_start or event_start >= local_end:
                        continue
                    status = str(row.get("Status", "On"))
                    summary = f"{names.get(item_uuid, 'Poolside schedule')} — {status}"
                    events.append(
                        ScheduleEvent(
                            item_uuid=item_uuid,
                            summary=summary,
                            start=event_start,
                            end=event_end,
                            status=status,
                        )
                    )
    return sorted(events, key=lambda event: (event.start, event.end, event.item_uuid))


class ScheduleMutationGate:
    """Fail closed until a remote atomic conflict contract is captured."""

    async def async_mutate(self, _document: Mapping[str, Any]) -> None:
        """Reject every mutation before a transport can be called."""
        raise ScheduleMutationUnavailableError(
            "Schedule writes require a confirmed remote conflict mechanism"
        )
