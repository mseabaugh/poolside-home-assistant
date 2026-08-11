"""Home Assistant lifecycle, reconciliation, and push coordination."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import PoolsideClient
from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    HEARTBEAT_INTERVAL_SECONDS,
    PUSH_RECONNECT_MAX_SECONDS,
    PUSH_RECONNECT_MIN_SECONDS,
)
from .exceptions import (
    AuthenticationError,
    CannotConnectError,
    FlowConfirmationRequiredError,
    PoolsideError,
)
from .models import PoolsideData, RouteGroup, Site

_LOGGER = logging.getLogger(__name__)
_REFRESH_PUSH_METHODS = frozenset(
    {
        "Device.setConfig",
        "Site.setDesiredState",
        "Site.setStates",
        "Site.updateAlerts",
    }
)
_FLOW_SCOPE_CONTROL_TYPES = frozenset({"filter", "circulation", "circulationcontrol"})
_ACTIVE_FLOW_STATUSES = frozenset({"on", "running", "active"})


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
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._pending_controls: dict[tuple[str, str], dict[str, object]] = {}
        # Active body is the last confirmed Poolside flow state. Changes are
        # accepted only through the server-side procedure below.
        self._active_bodies: dict[tuple[str, str], str | None] = {}
        self._flow_transitions: dict[tuple[str, str], dict[str, object]] = {}
        # Dashboard context is intentionally separate from confirmed hydraulic
        # state.  Choosing Pool/Spa changes what the card renders, never valves.
        self._dashboard_contexts: dict[tuple[str, str], str | None] = {}
        self._route_selections: dict[tuple[str, str], str | None] = {}

    def _apply_pending_controls(self, data: PoolsideData) -> PoolsideData:
        """Overlay successful local writes until the cloud snapshot confirms them."""
        sites = dict(data.sites)
        for (site_uuid, control_uuid), changes in tuple(self._pending_controls.items()):
            site = sites.get(site_uuid)
            control = site.all_controls.get(control_uuid) if site else None
            if site is None or control is None:
                continue
            if all(control.desired.get(key) == value for key, value in changes.items()):
                self._pending_controls.pop((site_uuid, control_uuid), None)
                continue
            updated = replace(control, desired={**control.desired, **changes})
            ordinary = dict(site.controls)
            combined = dict(site.combined_controls)
            (combined if control_uuid in combined else ordinary)[control_uuid] = updated
            sites[site_uuid] = replace(site, controls=ordinary, combined_controls=combined)
        return replace(data, sites=sites)

    def _sync_confirmed_body_modes(self, data: PoolsideData) -> None:
        """Synchronize each body group from confirmed high-level flow state.

        This is intentionally a read-only interpretation of Poolside's reported
        desired state.  Physical equipment telemetry and unrecognized controls
        cannot establish a body mode.  An incomplete or conflicting report is
        represented as Off rather than guessed.
        """
        for site in data.sites.values():
            for group in site.body_connection_groups:
                active_bodies = {
                    control.water_body_uuid
                    for control in site.all_controls.values()
                    if control.water_body_uuid in group
                    and control.type.lower() in _FLOW_SCOPE_CONTROL_TYPES
                    and str(control.desired.get("Status", "")).lower() in _ACTIVE_FLOW_STATUSES
                }
                group_key = "|".join(sorted(group))
                if len(active_bodies) == 1:
                    self._active_bodies[(site.uuid, group_key)] = next(iter(active_bodies))
                elif len(active_bodies) > 1:
                    self._active_bodies[(site.uuid, group_key)] = None

    async def _async_update_data(self) -> PoolsideData:
        """Fetch a complete consistent account snapshot."""
        _LOGGER.debug("poolside_refresh outcome=started")
        try:
            data = self._apply_pending_controls(await self.client.async_load())
        except AuthenticationError as err:
            _LOGGER.warning("poolside_refresh outcome=authentication_error")
            raise ConfigEntryAuthFailed from err
        except (CannotConnectError, PoolsideError) as err:
            details = {"error_type": type(err).__name__}
            if isinstance(err, CannotConnectError):
                if err.status is not None:
                    details["status"] = str(err.status)
                if err.content_type is not None:
                    details["content_type"] = err.content_type
            _LOGGER.warning(
                "poolside_refresh outcome=failed %s",
                " ".join(f"{key}={value}" for key, value in details.items()),
            )
            raise UpdateFailed("Poolside refresh failed") from err
        else:
            self._sync_confirmed_body_modes(data)
            _LOGGER.debug("poolside_refresh outcome=success site_count=%s", len(data.sites))
            return data

    def start_push(self) -> None:
        """Start reconnecting push and authenticated heartbeat listeners."""
        if self._push_task is None:
            self._push_task = self.hass.async_create_background_task(
                self._async_push_loop(),
                "poolside_push_listener",
                eager_start=True,
            )
        if self._heartbeat_task is None:
            self._heartbeat_task = self.hass.async_create_background_task(
                self._async_heartbeat_loop(),
                "poolside_authentication_heartbeat",
                eager_start=True,
            )

    async def async_shutdown(self) -> None:
        """Stop background listeners without leaking tasks."""
        self._stopping.set()
        for task_name in ("_push_task", "_heartbeat_task"):
            task = getattr(self, task_name)
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            setattr(self, task_name, None)

    async def _async_heartbeat_loop(self) -> None:
        """Keep a sliding Poolside session active without persisting credentials."""
        while not self._stopping.is_set():
            try:
                await self.client.async_ping()
                _LOGGER.debug("poolside_heartbeat outcome=success")
            except AuthenticationError:
                self._poolside_entry.async_start_reauth(self.hass)
                return
            except CannotConnectError, PoolsideError:
                _LOGGER.debug("poolside_heartbeat outcome=retryable_failure")
            if not self._stopping.is_set():
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
                    )
                except TimeoutError:
                    continue

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

    def body_group_key(self, site_uuid: str, body_uuid: str) -> str:
        """Return a stable key for the explicit connected body component."""
        site = self.site(site_uuid)
        for group in site.body_connection_groups:
            if body_uuid in group:
                return "|".join(sorted(group))
        return body_uuid

    def active_body(self, site_uuid: str, group_key: str | None = None) -> str | None:
        """Return the controller-confirmed body for a group, or the first body."""
        active = getattr(self, "_active_bodies", {})
        if group_key is not None:
            return active.get((site_uuid, group_key))
        return next((body for (site, _group), body in active.items() if site == site_uuid), None)

    def dashboard_context(self, site_uuid: str, group_key: str) -> str | None:
        """Return the card's selected body context without changing equipment."""
        contexts = self._dashboard_contexts
        if (site_uuid, group_key) in contexts:
            return contexts[(site_uuid, group_key)]
        return self.active_body(site_uuid, group_key)

    def set_dashboard_context(self, site_uuid: str, group_key: str, body_uuid: str | None) -> None:
        """Set a validated dashboard-only body context and refresh listeners."""
        group = self._group_bodies(site_uuid, group_key)
        if not group:
            raise ValueError("Body group is not available")
        if body_uuid is not None and body_uuid not in group:
            raise ValueError("Body is not part of this group")
        self._dashboard_contexts[(site_uuid, group_key)] = body_uuid
        self.async_update_listeners()

    def body_is_visible(self, site_uuid: str, body_uuid: str | None) -> bool:
        """Keep discovered entities visible; availability is not dashboard context."""
        del site_uuid, body_uuid
        return True

    def flow_transition(self, site_uuid: str, group_key: str) -> dict[str, object] | None:
        """Return the current server-side flow transition, if one is pending."""
        return (getattr(self, "_flow_transitions", None) or {}).get((site_uuid, group_key))

    async def async_run_flow_switch(
        self, site_uuid: str, group_key: str, body_uuid: str | None
    ) -> None:
        """Request one safe Poolside flow transition and await confirmation."""
        site = self.site(site_uuid)
        if body_uuid is not None and body_uuid not in self._group_bodies(site_uuid, group_key):
            raise ValueError("Body is not part of this flow group")
        started = datetime.now(UTC)
        transition = {
            "state": "Preparing",
            # This ID deliberately identifies only this local log/event span.
            # Poolside/site/body identifiers must not leak into HA state or logs.
            "correlation_id": uuid4().hex[:12],
            "started": started.isoformat(),
        }
        transitions = getattr(self, "_flow_transitions", None)
        if transitions is None:
            transitions = {}
            self._flow_transitions = transitions
        transitions[(site_uuid, group_key)] = transition
        self.async_update_listeners()
        try:
            transition["state"] = "Stopping circulation"
            self.async_update_listeners()
            result = await asyncio.wait_for(
                self.client.async_run_flow_switch(site, body_uuid), timeout=60
            )
            if result is False:
                raise PoolsideError("Poolside rejected the flow transition")
            transition["state"] = "Moving valves"
            self.async_update_listeners()
            transition["state"] = "Starting circulation"
            self.async_update_listeners()
            # Safety-critical confirmation cannot use the debounced refresh
            # scheduler: a recent poll may otherwise leave the previous body
            # cached while the controller has already moved its valves.
            await self.async_refresh()
            confirmed = self.active_body(site_uuid, group_key)
            if body_uuid is not None and confirmed != body_uuid:
                raise PoolsideError("Poolside did not confirm the requested body")
            transition["state"] = "Confirmed"
            transition["completed"] = datetime.now(UTC).isoformat()
            _LOGGER.info(
                "poolside_flow_transition outcome=confirmed correlation_id=%s duration_ms=%s",
                transition["correlation_id"],
                round((datetime.now(UTC) - started).total_seconds() * 1000),
            )
        except Exception as err:
            transition["state"] = "Timed out" if isinstance(err, TimeoutError) else "Failed"
            transition["error_type"] = type(err).__name__
            _LOGGER.warning(
                "poolside_flow_transition outcome=failed correlation_id=%s error_type=%s",
                transition["correlation_id"],
                type(err).__name__,
            )
            raise
        finally:
            self._flow_transitions.pop((site_uuid, group_key), None)
            self.async_update_listeners()

    def _group_bodies(self, site_uuid: str, group_key: str) -> frozenset[str]:
        """Resolve a stable group key to its discovered body UUIDs."""
        site = self.site(site_uuid)
        return next(
            (
                group
                for group in site.body_connection_groups
                if "|".join(sorted(group)) == group_key
            ),
            frozenset(),
        )

    def _route_group(self, site_uuid: str, route_key: str) -> RouteGroup | None:
        """Resolve one discovered route group without trusting a display label."""
        return next(
            (group for group in self.site(site_uuid).route_groups if group.key == route_key),
            None,
        )

    def route_selection(self, site_uuid: str, route_key: str) -> str | None:
        """Return one selected route Control, or None for a controller Blend."""
        route = self._route_group(site_uuid, route_key)
        if route is None:
            raise ValueError("Route group is not available")
        selections = self._route_selections
        selected = selections.get((site_uuid, route_key))
        if selected is None and (site_uuid, route_key) in selections:
            return None
        if selected in route.control_uuids:
            return selected
        on_controls = tuple(
            control_uuid
            for control_uuid in route.control_uuids
            if str(
                self.site(site_uuid).all_controls[control_uuid].desired.get("Status", "OFF")
            ).upper()
            == "ON"
        )
        if len(on_controls) == 1:
            return on_controls[0]
        if len(on_controls) > 1:
            return None
        return route.control_uuids[0]

    def set_route_selection(self, site_uuid: str, route_key: str, control_uuid: str | None) -> None:
        """Select a route view, with None representing an allowed Blend view."""
        route = self._route_group(site_uuid, route_key)
        if route is None:
            raise ValueError("Route group is not available")
        if control_uuid is not None and control_uuid not in route.control_uuids:
            raise ValueError("Control is not part of this route group")
        self._route_selections[(site_uuid, route_key)] = control_uuid
        self.async_update_listeners()

    async def async_set_route_enabled(
        self, site_uuid: str, route_key: str, *, enabled: bool
    ) -> None:
        """Atomically apply one verified route selection through high-level Controls."""
        site = self.site(site_uuid)
        route = self._route_group(site_uuid, route_key)
        if route is None:
            raise ValueError("Route group is not available")
        body_group_key = self.body_group_key(site_uuid, route.body_uuid)
        if self.active_body(site_uuid, body_group_key) != route.body_uuid:
            raise PoolsideError("Route body is not the confirmed water-flow state")
        selected = self.route_selection(site_uuid, route_key)
        targets = route.control_uuids if selected is None else (selected,)
        changes: dict[str, dict[str, object]] = {
            control_uuid: {"Status": "ON" if enabled and control_uuid in targets else "OFF"}
            for control_uuid in route.control_uuids
        }
        result = await self.client.async_set_controls(site, changes)
        if result is False:
            raise PoolsideError("Poolside rejected the feature-route update")
        self._pending_controls.update(
            {(site_uuid, control_uuid): change for control_uuid, change in changes.items()}
        )
        await self.async_request_refresh()

    async def async_turn_off_flow_group(self, site_uuid: str, group_key: str) -> None:
        """Turn off discovered water-flow Controls in one connected group in one batch."""
        site = self.site(site_uuid)
        group = self._group_bodies(site_uuid, group_key)
        if not group:
            raise ValueError("Body group is not available")
        controls = tuple(
            control
            for control in site.flow_controls_for_group(group)
            if str(control.desired.get("Status", "OFF")).lower() in _ACTIVE_FLOW_STATUSES
        )
        if any(not control.available for control in controls):
            raise PoolsideError("A running water-flow Control is currently restricted")
        changes: dict[str, dict[str, object]] = {
            control.uuid: {"Status": "OFF"} for control in controls
        }
        if changes:
            result = await self.client.async_set_controls(site, changes)
            if result is False:
                raise PoolsideError("Poolside rejected the water-flow shutdown")
            self._pending_controls.update(
                {(site_uuid, control_uuid): change for control_uuid, change in changes.items()}
            )
            await self.async_request_refresh()
        if self.active_body(site_uuid, group_key) is not None:
            raise PoolsideError("Poolside did not confirm water flow is off")
        self.set_dashboard_context(site_uuid, group_key, None)
        _LOGGER.info("poolside_flow_shutdown outcome=confirmed control_count=%s", len(changes))

    def set_active_body(
        self, site_uuid: str, body_uuid: str | None, group_key: str | None = None
    ) -> None:
        """Set test/controller-confirmed state and refresh dependent entities."""
        if body_uuid is not None and body_uuid not in self.site(site_uuid).bodies_of_water:
            raise ValueError("Body of water is not available")
        active_bodies = getattr(self, "_active_bodies", None)
        if active_bodies is None:
            active_bodies = self._active_bodies = {}
        if body_uuid is not None:
            group_key = group_key or self.body_group_key(site_uuid, body_uuid)
        if group_key is None:
            raise ValueError("A body group is required to select Off")
        active_bodies[(site_uuid, group_key)] = body_uuid
        self.async_update_listeners()

    async def async_set_control(
        self,
        site_uuid: str,
        control_uuid: str,
        changes: dict[str, object],
    ) -> None:
        """Write one safe Control mutation and reconcile confirmation."""
        site = self.site(site_uuid)
        control = site.all_controls.get(control_uuid)
        activating = str(changes.get("Status", "")).lower() in _ACTIVE_FLOW_STATUSES
        if control and activating and control.is_water_flow_control and control.water_body_uuid:
            group_key = self.body_group_key(site_uuid, control.water_body_uuid)
            if self.active_body(site_uuid, group_key) != control.water_body_uuid:
                raise FlowConfirmationRequiredError(
                    "Confirm the body-flow change in the Poolside dashboard"
                )
        await self.client.async_set_control(site, control_uuid, changes)
        self._pending_controls[(site_uuid, control_uuid)] = dict(changes)
        await self.async_request_refresh()

    async def async_activate_theme(self, site_uuid: str, theme_uuid: str) -> None:
        """Activate one safe Theme and reconcile confirmation."""
        await self.client.async_activate_theme(self.site(site_uuid), theme_uuid)
        await self.async_request_refresh()
