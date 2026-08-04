"""Home Assistant lifecycle, reconciliation, and push coordination."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import PoolsideClient
from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    PUSH_RECONNECT_MAX_SECONDS,
    PUSH_RECONNECT_MIN_SECONDS,
)
from .exceptions import AuthenticationError, CannotConnectError, PoolsideError
from .models import PoolsideData, Site

_LOGGER = logging.getLogger(__name__)
_REFRESH_PUSH_METHODS = frozenset(
    {
        "Device.setConfig",
        "Site.setDesiredState",
        "Site.setStates",
        "Site.updateAlerts",
    }
)


class PoolsideCoordinator(DataUpdateCoordinator[PoolsideData]):
    """Own snapshots, writes, push reconnects, and periodic reconciliation."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: PoolsideClient,
    ) -> None:
        """Initialize with an injected typed client."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self._poolside_entry = config_entry
        self._push_task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def _async_update_data(self) -> PoolsideData:
        """Fetch a complete consistent account snapshot."""
        try:
            return await self.client.async_load()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except (CannotConnectError, PoolsideError) as err:
            raise UpdateFailed("Poolside refresh failed") from err

    def start_push(self) -> None:
        """Start one reconnecting background push listener."""
        if self._push_task is None:
            self._push_task = self.hass.async_create_background_task(
                self._async_push_loop(),
                "poolside_push_listener",
                eager_start=True,
            )

    async def async_shutdown(self) -> None:
        """Stop the push listener without leaking a background task."""
        self._stopping.set()
        if self._push_task is None:
            return
        self._push_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._push_task
        self._push_task = None

    async def _async_push_loop(self) -> None:
        """Reconnect with bounded exponential backoff and no busy loop."""
        backoff = PUSH_RECONNECT_MIN_SECONDS
        while not self._stopping.is_set():
            try:
                async for method, _params in self.client.async_push_messages():
                    backoff = PUSH_RECONNECT_MIN_SECONDS
                    if method in _REFRESH_PUSH_METHODS:
                        await self.async_request_refresh()
                    elif method != "Connection.activate":
                        _LOGGER.debug("poolside_push outcome=ignored method=%s", method)
            except AuthenticationError:
                self._poolside_entry.async_start_reauth(self.hass)
                return
            except CannotConnectError, PoolsideError:
                _LOGGER.debug("poolside_push outcome=reconnect backoff_seconds=%s", backoff)
            if not self._stopping.is_set():
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=backoff)
                except TimeoutError:
                    backoff = min(backoff * 2, PUSH_RECONNECT_MAX_SECONDS)

    def site(self, site_uuid: str) -> Site:
        """Return one current site snapshot."""
        return self.data.sites[site_uuid]

    async def async_set_control(
        self,
        site_uuid: str,
        control_uuid: str,
        changes: dict[str, object],
    ) -> None:
        """Write one safe Control mutation and reconcile confirmation."""
        await self.client.async_set_control(self.site(site_uuid), control_uuid, changes)
        await self.async_request_refresh()

    async def async_activate_theme(self, site_uuid: str, theme_uuid: str) -> None:
        """Activate one safe Theme and reconcile confirmation."""
        await self.client.async_activate_theme(self.site(site_uuid), theme_uuid)
        await self.async_request_refresh()
