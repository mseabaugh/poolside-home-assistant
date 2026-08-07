"""Tests for integration bootstrap behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant

from custom_components import poolside

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
        (hass, "/poolside/poolside-body-selector.js"),
        (hass, "/poolside/poolside-dashboard.js"),
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
        (hass, "/poolside/poolside-body-selector.js"),
        (hass, "/poolside/poolside-dashboard.js"),
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
        (hass, "/poolside/poolside-body-selector.js"),
        (hass, "/poolside/poolside-dashboard.js"),
    ]
