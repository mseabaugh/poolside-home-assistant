"""Poolside Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .client import PoolsideClient
from .const import PLATFORMS, VERSION
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
    _register_frontend_modules(hass)


def _register_frontend_modules(hass: HomeAssistant) -> None:
    """Register card modules, deferring until frontend setup when necessary.

    Integrations can be initialized before the built-in frontend component. A
    premature write to the frontend data key is unsafe because frontend setup
    replaces that value with its URL manager. Waiting for Home Assistant to be
    fully started preserves the registration across all startup orders.
    """
    if DATA_EXTRA_MODULE_URL not in hass.data:
        if not hass.data.get("poolside_frontend_listener"):
            hass.data["poolside_frontend_listener"] = True

            async def _register_after_start(_event: object) -> None:
                _register_frontend_modules(hass)

            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED,
                _register_after_start,
            )
        return

    # Home Assistant's frontend aggressively caches JavaScript modules.  A
    # release-specific query value both preserves local installation and makes
    # every integration update load the matching bundled card implementation.
    add_extra_js_url(hass, f"/poolside/poolside-body-selector.js?v={VERSION}")
    add_extra_js_url(hass, f"/poolside/poolside-dashboard.js?v={VERSION}")


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
    _remove_legacy_native_control_entities(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start_push()
    return True


def _remove_legacy_native_control_entities(
    hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    coordinator: PoolsideCoordinator,
) -> None:
    """Remove superseded switch/number entities after a native-control migration.

    Versions before 0.1.31 represented variable-speed blowers and setpoint-capable
    heaters as independent switch and number entities.  Those registry entries are
    not automatically removed when the native Fan or Climate platform takes over,
    leaving unavailable duplicates in the device UI.  Remove only the known legacy
    unique IDs for controls whose *discovered schema* qualifies for the replacement;
    this never infers a new writable capability from telemetry.
    """
    legacy_unique_ids: set[tuple[str, str]] = set()
    for site in coordinator.data.sites.values():
        for control in site.all_controls.values():
            if control.is_blower and control.supports_percentage:
                legacy_unique_ids.update(
                    {
                        ("switch", control.uuid),
                        ("number", f"{control.uuid}_power_level"),
                    }
                )
            if control.supports_temperature_setpoint:
                legacy_unique_ids.update(
                    {
                        ("switch", control.uuid),
                        ("number", f"{control.uuid}_power_level"),
                        ("number", f"{control.uuid}_temperature"),
                    }
                )

    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            registry_entry.platform == "poolside"
            and (registry_entry.domain, registry_entry.unique_id) in legacy_unique_ids
        ):
            registry.async_remove(registry_entry.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: PoolsideConfigEntry) -> bool:
    """Unload platforms and stop every background resource."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.async_shutdown()
    return True
