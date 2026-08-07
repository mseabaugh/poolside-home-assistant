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


async def _async_register_frontend_assets(hass: HomeAssistant) -> None:
    """Register bundled frontend assets when the frontend stack is ready."""
    www = Path(__file__).parent / "www"
    if hass.http is not None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/poolside", str(www), cache_headers=False)]
        )
    if "frontend_extra_module_url" in hass.data:
        add_extra_js_url(hass, "/poolside/poolside-body-selector.js")
        add_extra_js_url(hass, "/poolside/poolside-dashboard.js")


async def async_setup(hass: HomeAssistant, _config: dict[str, object]) -> bool:
    """Register bundled frontend assets on the local Home Assistant HTTP server."""
    await _async_register_frontend_assets(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PoolsideConfigEntry) -> bool:
    """Set up Poolside from a UI-created config entry."""
    # Re-register after config-entry startup so an already-running frontend also
    # receives the local card resource.
    await _async_register_frontend_assets(hass)
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
