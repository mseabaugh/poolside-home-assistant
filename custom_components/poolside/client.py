"""Typed Poolside operations and safety-enforced write façade."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from .exceptions import ProtocolError
from .models import PoolsideData, Site, apply_runtime, discover_sites
from .redact import fingerprint
from .safety import SafetyPolicy
from .transport import Transport


class PoolsideClient:
    """Expose only confirmed Poolside operations to the Home Assistant layer."""

    def __init__(self, transport: Transport, safety: SafetyPolicy | None = None) -> None:
        """Initialize with injected external resources."""
        self._transport = transport
        self._safety = safety or SafetyPolicy()

    async def async_ping(self) -> bool:
        """Validate connectivity and authentication."""
        result = await self._transport.async_rpc("ping")
        if result is not True:
            raise ProtocolError("Poolside ping did not return true")
        return True

    async def async_get_config(self) -> Any:
        """Fetch the complete account configuration."""
        return await self._transport.async_rpc("User.getConfig", {})

    async def async_get_states(self, site_uuid: str | int) -> Any:
        """Fetch current string-serialized equipment state."""
        return await self._transport.async_rpc("Site.getStates", {"site": {"siteId": site_uuid}})

    async def async_get_desired_state(self, site_uuid: str | int) -> Any:
        """Fetch current high-level desired-state records."""
        return await self._transport.async_rpc("Site.getDesiredState", {"siteId": site_uuid})

    async def async_validate(self) -> str:
        """Validate a credential and return a non-reversible account fingerprint."""
        await self.async_ping()
        data = discover_sites(await self.async_get_config())
        if data.empty:
            raise ProtocolError("Poolside account did not contain a site")
        return fingerprint(*data.sites)

    async def async_load(self) -> PoolsideData:
        """Discover all sites and merge runtime states concurrently."""
        discovered = discover_sites(await self.async_get_config())
        if discovered.empty:
            return discovered
        site_ids = tuple(discovered.sites)
        remote_ids = tuple(discovered.sites[site_uuid].remote_id for site_uuid in site_ids)
        state_tasks = [self.async_get_states(remote_id) for remote_id in remote_ids]
        desired_tasks = [self.async_get_desired_state(remote_id) for remote_id in remote_ids]
        runtime = await asyncio.gather(*state_tasks, *desired_tasks)
        split = len(site_ids)
        states = runtime[:split]
        desired = runtime[split:]
        sites = {
            site_uuid: apply_runtime(discovered.sites[site_uuid], states[index], desired[index])
            for index, site_uuid in enumerate(site_ids)
        }
        return PoolsideData(sites)

    async def async_set_control(
        self,
        site: Site,
        target_uuid: str,
        changes: Mapping[str, Any],
    ) -> Any:
        """Merge and write one latest full desired-state record after authorization."""
        control = self._safety.authorize_control(site, target_uuid, changes)
        desired = dict(control.desired)
        if not desired:
            desired["ControlUUID"] = control.uuid
        desired.update(changes)
        desired["ControlUUID"] = control.uuid
        return await self._transport.async_rpc(
            "Site.setDesiredState2",
            {
                "BatchUUID": str(uuid4()),
                "SiteUUID": site.uuid,
                "DesiredStates": [desired],
            },
        )

    async def async_activate_theme(self, site: Site, theme_uuid: str) -> Any:
        """Activate one discovered Theme using the only confirmed status."""
        theme = self._safety.authorize_theme(site, theme_uuid, "ON")
        return await self._transport.async_rpc(
            "Site.setTheme",
            {"Status": "ON", "UUID": theme.uuid, "siteUuid": site.uuid},
        )

    async def async_push_messages(self) -> AsyncIterator[tuple[str, Mapping[str, Any]]]:
        """Yield known and unknown push methods without exposing their bodies to logs."""
        async for payload in self._transport.async_messages():
            method = payload.get("method")
            params = payload.get("params", {})
            if isinstance(method, str) and isinstance(params, Mapping):
                yield method, params

    @staticmethod
    def replace_site(data: PoolsideData, site: Site) -> PoolsideData:
        """Return a new coordinator payload containing one replaced site."""
        sites = dict(data.sites)
        sites[site.uuid] = site
        return replace(data, sites=sites)
