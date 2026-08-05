"""Poolside Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant

from .client import PoolsideClient
from .const import PLATFORMS
from .coordinator import PoolsideCoordinator
from .factory import create_client


@dataclass(slots=True)
class PoolsideRuntimeData:
    """Runtime resources owned by one config entry."""

    client: PoolsideClient
    coordinator: PoolsideCoordinator


type PoolsideConfigEntry = ConfigEntry[PoolsideRuntimeData]


async def async_setup(hass: HomeAssistant, _config: dict[str, object]) -> bool:
    """Register bundled frontend assets on the local Home Assistant HTTP server."""
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/poolside", str(www), cache_headers=True)]
    )
    add_extra_js_url(hass, "/poolside/poolside-body-selector.js")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PoolsideConfigEntry) -> bool:
    """Set up Poolside from a UI-created config entry."""
    client = create_client(hass, entry.data[CONF_ACCESS_TOKEN])
    coordinator = PoolsideCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = PoolsideRuntimeData(client, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start_push()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PoolsideConfigEntry) -> bool:
    """Unload platforms and stop every background resource."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.async_shutdown()
    return True
