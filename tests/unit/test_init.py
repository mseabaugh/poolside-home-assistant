"""Tests for integration bootstrap behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components import poolside
from custom_components.poolside.const import DOMAIN, VERSION
from custom_components.poolside.models import BodyOfWater, PoolsideData, Site
from custom_components.poolside.redact import fingerprint

pytestmark = pytest.mark.unit


class DummyHTTP:
    """Capture static path registrations."""

    def __init__(self) -> None:
        self.paths: list[StaticPathConfig] = []

    async def async_register_static_paths(self, paths: list[StaticPathConfig]) -> None:
        self.paths = paths


class DummyBus:
    """Capture one-shot startup listeners."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.callbacks: list[tuple[str, Any]] = []

    def async_listen_once(self, event: str, callback: Any) -> None:
        self.callbacks.append((event, callback))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


async def test_async_setup_registers_frontend_assets_when_http_is_available(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frontend bundle is still registered when Home Assistant HTTP exists."""
    dummy_http = DummyHTTP()
    captured_urls: list[tuple[Any, str]] = []
    monkeypatch.setattr(
        poolside,
        "add_extra_js_url",
        lambda hass_arg, url: captured_urls.append((hass_arg, url)),
    )
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda _change, _url: None, [])
    monkeypatch.setattr(hass, "http", dummy_http, raising=False)
    assert await poolside.async_setup(hass, {})

    assert dummy_http.paths == [
        StaticPathConfig(
            "/poolside",
            str(Path(poolside.__file__).parent / "www"),
            cache_headers=False,
        )
    ]
    assert captured_urls == [
        (hass, f"/poolside/poolside-body-selector.js?v={VERSION}"),
        (hass, f"/poolside/poolside-dashboard.js?v={VERSION}"),
    ]


async def test_async_setup_skips_static_registration_when_http_is_missing(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup should remain safe in the test harness when HTTP is not initialized."""
    captured_urls: list[tuple[Any, str]] = []
    monkeypatch.setattr(
        poolside,
        "add_extra_js_url",
        lambda hass_arg, url: captured_urls.append((hass_arg, url)),
    )
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda _change, _url: None, [])
    monkeypatch.setattr(hass, "http", None, raising=False)

    assert await poolside.async_setup(hass, {})

    assert captured_urls == [
        (hass, f"/poolside/poolside-body-selector.js?v={VERSION}"),
        (hass, f"/poolside/poolside-dashboard.js?v={VERSION}"),
    ]


async def test_frontend_module_registration_defers_until_frontend_is_ready(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A startup-order race must not lose the bundled card URLs."""
    captured_urls: list[tuple[Any, str]] = []
    dummy_bus = DummyBus(hass.bus)
    monkeypatch.setattr(
        poolside,
        "add_extra_js_url",
        lambda hass_arg, url: captured_urls.append((hass_arg, url)),
    )
    monkeypatch.setattr(hass, "bus", dummy_bus, raising=False)

    poolside._register_frontend_modules(hass)

    assert dummy_bus.callbacks
    assert dummy_bus.callbacks[0][0] == EVENT_HOMEASSISTANT_STARTED
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda _change, _url: None, [])
    await dummy_bus.callbacks[0][1](object())
    assert captured_urls == [
        (hass, f"/poolside/poolside-body-selector.js?v={VERSION}"),
        (hass, f"/poolside/poolside-dashboard.js?v={VERSION}"),
    ]


async def test_confirm_flow_service_resolves_only_opaque_discovered_ids(
    hass: HomeAssistant,
) -> None:
    """The dashboard service resolves one discovered group without exposing UUIDs."""
    pool = BodyOfWater("pool-id", "Pool", "Pool", "site-id")
    spa = BodyOfWater(
        "spa-id",
        "Spa",
        "Spa",
        "site-id",
        {"Spillover": {"ConnectedThings": [{"UUID": "pool-id"}]}},
    )
    site = Site("site-id", "Synthetic", bodies_of_water={pool.uuid: pool, spa.uuid: spa})
    coordinator = SimpleNamespace(
        data=PoolsideData({site.uuid: site}),
        async_run_flow_switch=AsyncMock(),
        set_dashboard_context=Mock(),
    )
    hass.data[poolside._COORDINATORS] = {"entry": coordinator}
    poolside._register_flow_confirmation_service(hass)
    poolside._register_flow_confirmation_service(hass)
    group_key = "pool-id|spa-id"
    data = {
        poolside.ATTR_GROUP_ID: fingerprint(group_key)[:12],
        poolside.ATTR_BODY_ID: fingerprint(spa.uuid)[:12],
    }

    await hass.services.async_call(
        DOMAIN,
        poolside.SERVICE_CONFIRM_FLOW_SWITCH,
        data,
        blocking=True,
    )
    coordinator.async_run_flow_switch.assert_awaited_once_with(site.uuid, group_key, spa.uuid)
    coordinator.set_dashboard_context.assert_called_once_with(site.uuid, group_key, spa.uuid)

    with pytest.raises(HomeAssistantError, match="not uniquely available"):
        await hass.services.async_call(
            DOMAIN,
            poolside.SERVICE_CONFIRM_FLOW_SWITCH,
            {**data, poolside.ATTR_GROUP_ID: "unknown-group"},
            blocking=True,
        )
    with pytest.raises(HomeAssistantError, match="not uniquely available"):
        await hass.services.async_call(
            DOMAIN,
            poolside.SERVICE_CONFIRM_FLOW_SWITCH,
            {**data, poolside.ATTR_BODY_ID: "unknown-body"},
            blocking=True,
        )
    hass.services.async_remove(DOMAIN, poolside.SERVICE_CONFIRM_FLOW_SWITCH)


async def test_unload_keeps_shared_flow_service_for_another_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unloading one account cannot remove the service used by another account."""
    coordinator = SimpleNamespace(async_shutdown=AsyncMock())
    entry = SimpleNamespace(
        entry_id="departing-entry",
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    hass.data[poolside._COORDINATORS] = {
        entry.entry_id: coordinator,
        "remaining-entry": object(),
    }
    monkeypatch.setattr(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=True),
    )
    hass.services.async_register(DOMAIN, poolside.SERVICE_CONFIRM_FLOW_SWITCH, AsyncMock())

    assert await poolside.async_unload_entry(hass, entry)  # type: ignore[arg-type]
    assert hass.services.has_service(DOMAIN, poolside.SERVICE_CONFIRM_FLOW_SWITCH)
    coordinator.async_shutdown.assert_awaited_once()
    hass.services.async_remove(DOMAIN, poolside.SERVICE_CONFIRM_FLOW_SWITCH)
