"""Unit coverage for read-only schedule projection and mutation gating."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.poolside.exceptions import ScheduleMutationUnavailableError
from custom_components.poolside.schedule import (
    ScheduleMutationGate,
    canonical_hash,
    schedule_events,
)

pytestmark = pytest.mark.unit


def test_canonical_hash_is_order_independent_and_unicode_stable() -> None:
    """Equivalent documents receive the same local stale-data fingerprint."""
    first = {"b": 2, "a": {"name": "café"}}
    second = {"a": {"name": "café"}, "b": 2}
    assert canonical_hash(first) == canonical_hash(second)
    assert canonical_hash(first) != canonical_hash({"a": {"name": "cafe"}, "b": 2})


def test_schedule_events_include_day_and_overnight_occurrences(
    user_config: dict[str, object],
) -> None:
    """Weekly exact-time rows project into bounded timezone-aware events."""
    document = user_config["Sites"][0]["Schedule"]  # type: ignore[index]
    timezone = ZoneInfo("America/Chicago")
    start = datetime(2026, 8, 3, 0, 0, tzinfo=timezone)
    end = datetime(2026, 8, 4, 2, 0, tzinfo=timezone)
    events = schedule_events(document, start, end, timezone, {"filter-one": "Filter"})
    assert [event.summary for event in events] == ["Filter — On", "Filter — On"]
    assert events[0].start.hour == 8
    assert events[0].end.hour == 10
    assert events[1].start.hour == 23
    assert events[1].end.day == 4
    assert events[1].end.hour == 1


def test_schedule_events_are_conservative_for_unknown_shapes() -> None:
    """Invalid ranges, documents, days, times, and rows are ignored safely."""
    timezone = ZoneInfo("UTC")
    start = datetime(2026, 8, 3, tzinfo=timezone)
    end = datetime(2026, 8, 10, tzinfo=timezone)
    assert schedule_events({}, start, start, timezone) == []
    assert schedule_events({"Schedule": "bad"}, start, end, timezone) == []
    document = {
        "Schedule": [
            None,
            {"ItemUUID": 1, "ScheduleElements": []},
            {"ItemUUID": "x", "ScheduleElements": "bad"},
            {
                "ItemUUID": "x",
                "ScheduleElements": [
                    None,
                    {"Day": "Funday", "Times": []},
                    {"Day": "Monday", "Times": "bad"},
                    {
                        "Day": "Monday",
                        "Times": [
                            None,
                            {"StartTime": 1, "EndTime": "02:00"},
                            {"StartTime": "bad", "EndTime": "02:00"},
                            {"StartTime": "01:00", "EndTime": "bad"},
                            {"StartTime": "01:00", "EndTime": "02:00", "Status": "Off"},
                        ],
                    },
                ],
            },
        ]
    }
    events = schedule_events(document, start, end, timezone)
    assert len(events) == 1
    assert events[0].summary == "Poolside schedule — Off"


def test_schedule_range_excludes_outside_occurrences() -> None:
    """Occurrences that do not overlap the requested window are excluded."""
    timezone = ZoneInfo("UTC")
    document = {
        "Schedule": [
            {
                "ItemUUID": "x",
                "ScheduleElements": [
                    {
                        "Day": "Monday",
                        "Times": [
                            {"StartTime": "01:00", "EndTime": "02:00"},
                            {"StartTime": "20:00", "EndTime": "21:00"},
                        ],
                    }
                ],
            }
        ]
    }
    start = datetime(2026, 8, 3, 10, 0, tzinfo=timezone)
    end = datetime(2026, 8, 3, 12, 0, tzinfo=timezone)
    assert schedule_events(document, start, end, timezone) == []


async def test_schedule_mutation_gate_fails_before_transport() -> None:
    """Every schedule mutation remains unavailable without atomic remote conflicts."""
    with pytest.raises(ScheduleMutationUnavailableError, match="conflict mechanism"):
        await ScheduleMutationGate().async_mutate({"Schedule": []})
