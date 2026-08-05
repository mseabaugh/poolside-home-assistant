"""Integration tests for setup, entities, writes, diagnostics, and unload."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolside import async_unload_entry
from custom_components.poolside.const import DOMAIN
from custom_components.poolside.diagnostics import async_get_config_entry_diagnostics
from custom_components.poolside.redact import REDACTED
from tests.fakes import FakeTransport

pytestmark = pytest.mark.integration


async def _setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    fake_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set up with an injected typed client."""
    monkeypatch.setattr("custom_components.poolside.create_client", lambda *_args: fake_client)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Resolve a deterministic entity ID by integration unique ID."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def test_setup_discovers_all_supported_safe_surfaces_and_unloads(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup creates expected local entities without exposing unconfirmed heating writes."""
    await _setup(hass, config_entry, fake_client, monkeypatch)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    assert len(entries) == 15
    assert _entity_id(hass, "light", "light-one")
    assert _entity_id(hass, "light", "light-combined")
    assert _entity_id(hass, "switch", "filter-one")
    assert er.async_get(hass).async_get_entity_id("switch", DOMAIN, "jets-restricted") is None
    assert _entity_id(hass, "number", "filter-one_power_level")
    assert _entity_id(hass, "button", "theme-calm_activate")
    assert _entity_id(hass, "select", "site-alpha_theme")
    assert _entity_id(hass, "calendar", "site-alpha_schedule")
    assert _entity_id(hass, "sensor", "pump-one_RPM")
    assert _entity_id(hass, "binary_sensor", "pump-one_Online")
    assert registry.async_get_entity_id("climate", DOMAIN, "heat-one") is None

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diagnostics["site_count"] == 1
    assert diagnostics["config_entry"]["access_token"] == REDACTED
    assert diagnostics["sites"][0]["controls"] == 4
    assert diagnostics["sites"][0]["equipment"] == 2
    assert diagnostics["sites"][0]["name"] == REDACTED
    assert "site-alpha" not in str(diagnostics)

    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_entity_services_reach_safe_transport_and_reconcile(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: Any,
    fake_transport: FakeTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service calls traverse HA entities, coordinator, safety, client, and transport."""
    await _setup(hass, config_entry, fake_client, monkeypatch)
    calls: list[tuple[str, str, dict[str, Any]]] = [
        (
            "switch",
            "turn_off",
            {"entity_id": _entity_id(hass, "switch", "filter-one")},
        ),
        (
            "light",
            "turn_on",
            {
                "brightness": 128,
                "entity_id": _entity_id(hass, "light", "light-one"),
                "rgb_color": [10, 20, 30],
            },
        ),
        (
            "number",
            "set_value",
            {
                "entity_id": _entity_id(hass, "number", "filter-one_power_level"),
                "value": 30,
            },
        ),
        (
            "button",
            "press",
            {"entity_id": _entity_id(hass, "button", "theme-calm_activate")},
        ),
        (
            "select",
            "select_option",
            {"entity_id": _entity_id(hass, "select", "site-alpha_theme"), "option": "Calm"},
        ),
    ]
    for domain, service, data in calls:
        await hass.services.async_call(domain, service, data, blocking=True)

    methods = [method for method, _params in fake_transport.calls]
    assert methods.count("Site.setDesiredState2") == 3
    assert methods.count("Site.setTheme") == 2
    light_write = next(
        params
        for method, params in fake_transport.calls
        if method == "Site.setDesiredState2"
        and params is not None
        and params["DesiredStates"][0]["ControlUUID"] == "light-one"
    )
    assert light_write["DesiredStates"][0]["Brightness"] == 50
    assert "10|20|30" in light_write["DesiredStates"][0]["Color"]

    assert er.async_get(hass).async_get_entity_id("switch", DOMAIN, "jets-restricted") is None
    assert not any(
        params is not None and "pump-one" in str(params)
        for method, params in fake_transport.calls
        if method.startswith("Site.set")
    )
    assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_platform_unload_failure_keeps_runtime(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A platform unload failure does not prematurely stop runtime resources."""
    await _setup(hass, config_entry, fake_client, monkeypatch)
    original_unload = hass.config_entries.async_unload_platforms
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", AsyncFalse())
    assert not await async_unload_entry(hass, config_entry)
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", original_unload)
    assert await hass.config_entries.async_unload(config_entry.entry_id)


class AsyncFalse:
    """Callable awaitable replacement for unload failure injection."""

    async def __call__(self, *_args: object) -> bool:
        return False
