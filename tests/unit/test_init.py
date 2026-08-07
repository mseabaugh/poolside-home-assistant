"""Tests for integration bootstrap behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from custom_components import poolside

pytestmark = pytest.mark.unit


class DummyHTTP:
    """Capture static path registrations."""

    def __init__(self) -> None:
        self.paths: list[StaticPathConfig] = []

    async def async_register_static_paths(self, paths: list[StaticPathConfig]) -> None:
        self.paths = paths


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
    monkeypatch.setattr(hass, "http", None, raising=False)

    assert await poolside.async_setup(hass, {})

    assert captured_urls == [
        (hass, "/poolside/poolside-body-selector.js"),
    ]
