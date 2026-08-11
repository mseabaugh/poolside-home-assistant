"""Integration tests for coordinator failure translation and push lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Coroutine
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolside.coordinator import PoolsideCoordinator
from custom_components.poolside.exceptions import (
    AuthenticationError,
    CannotConnectError,
    PoolsideError,
    ProtocolError,
)
from custom_components.poolside.models import (
    BodyOfWater,
    Control,
    PoolsideData,
    Site,
    apply_runtime,
    discover_sites,
)

pytestmark = pytest.mark.integration


class LoadClient:
    """Injected client that returns or raises one configured load result."""

    def __init__(self, result: PoolsideData | Exception) -> None:
        self.result = result

    async def async_load(self) -> PoolsideData:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def async_ping(self) -> bool:
        """Return a healthy heartbeat for coordinator lifecycle tests."""
        return True


class PushClient(LoadClient):
    """Scripted push client that exercises normal, reconnect, and auth paths."""

    def __init__(self) -> None:
        super().__init__(PoolsideData())
        self.calls = 0

    async def async_push_messages(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        self.calls += 1
        if self.calls == 1:
            yield "Site.setStates", {}
            yield "Connection.activate", {}
            yield "Unknown.push", {}
            return
        if self.calls == 2:
            raise CannotConnectError("synthetic")
        raise AuthenticationError("synthetic")


class HeartbeatClient(LoadClient):
    """Scripted heartbeat client for success, retry, and authentication paths."""

    def __init__(self, heartbeat_error: Exception | None = None) -> None:
        super().__init__(PoolsideData())
        self.heartbeat_error = heartbeat_error
        self.heartbeat_calls = 0

    async def async_ping(self) -> bool:
        self.heartbeat_calls += 1
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return True


class BatchClient(LoadClient):
    """Injected high-level Control batch writer for route safety coverage."""

    def __init__(self, result: PoolsideData, *, write_result: bool = True) -> None:
        super().__init__(result)
        self.write_result = write_result
        self.batches: list[dict[str, dict[str, object]]] = []

    async def async_set_controls(
        self, _site: object, changes: dict[str, dict[str, object]]
    ) -> bool:
        """Record the authorized batch without simulating any equipment write."""
        self.batches.append(changes)
        return self.write_result


def _route_site(user_config: dict[str, Any]) -> Site:
    """Build a synthetic controller-derived feature route with a pool/spa group."""
    discovered = discover_sites(user_config).sites["site-alpha"]
    pool = BodyOfWater("pool", "Pool", "Pool", discovered.uuid)
    spa = BodyOfWater(
        "spa",
        "Spa",
        "Spa",
        discovered.uuid,
        {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}},
    )
    filter_control = replace(
        discovered.controls["filter-one"],
        raw={"BodyOfWater": pool.uuid, "Type": "Filter"},
        desired={"Status": "ON", "PowerLevel": 60},
    )
    spillover = Control(
        "spillover-control",
        "Feature Spillover",
        "WaterFeature",
        discovered.uuid,
        desired={"Status": "ON", "PowerLevel": 65},
        raw={
            "BodyOfWater": pool.uuid,
            "ControlGroupUUID": "feature-group",
            "WaterFeature": True,
            "PowerLevelIncrements": [0, 50, 100],
        },
    )
    bubbler = replace(
        spillover,
        uuid="bubbler-control",
        name="Bubbler",
        desired={"Status": "OFF", "PowerLevel": 25},
    )
    light = replace(
        discovered.controls["light-one"],
        raw={"BodyOfWater": pool.uuid, "Type": "Light"},
        desired={"Status": "ON"},
    )
    return replace(
        discovered,
        bodies_of_water={pool.uuid: pool, spa.uuid: spa},
        controls={
            filter_control.uuid: filter_control,
            spillover.uuid: spillover,
            bubbler.uuid: bubbler,
            light.uuid: light,
        },
        flow_procedure={
            "ControlBasedProcedures": [
                {
                    "FlowUUID": "feature-flow",
                    "Procedures": [
                        {"ControlUUID": spillover.uuid},
                        {"ControlUUID": bubbler.uuid},
                    ],
                }
            ],
            "FlowBasedProcedures": [
                {
                    "FlowUUID": "feature-flow",
                    "FlatFlowAndPumpSpeeds": [
                        {
                            "FlatFlow": {
                                "Pump": "feature-pump",
                                "Return": [{"ActuatorUUID": "feature-return"}],
                            }
                        }
                    ],
                }
            ],
        },
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (AuthenticationError("synthetic"), ConfigEntryAuthFailed),
        (CannotConnectError("synthetic"), UpdateFailed),
        (ProtocolError("synthetic"), UpdateFailed),
    ],
)
async def test_update_translates_domain_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    failure: Exception,
    expected: type[Exception],
) -> None:
    """Authentication and availability failures map to Home Assistant contracts."""
    coordinator = PoolsideCoordinator(hass, config_entry, LoadClient(failure))  # type: ignore[arg-type]
    with pytest.raises(expected):
        await coordinator._async_update_data()
    await coordinator.async_shutdown()


async def test_stale_refresh_keeps_successful_local_control_write(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """A stale cloud response does not make a just-written control visibly bounce."""
    site = apply_runtime(discover_sites(user_config).sites["site-alpha"], {}, desired_payload)
    client: Any = LoadClient(PoolsideData({site.uuid: site}))
    coordinator = PoolsideCoordinator(hass, config_entry, client)
    coordinator._pending_controls[(site.uuid, "light-one")] = {"Status": "OFF"}
    data = coordinator._apply_pending_controls(PoolsideData({site.uuid: site}))
    assert data.sites[site.uuid].controls["light-one"].desired["Status"] == "OFF"
    assert (site.uuid, "light-one") in coordinator._pending_controls
    coordinator._pending_controls[(site.uuid, "light-one")] = {"Status": "ON"}
    confirmed = coordinator._apply_pending_controls(PoolsideData({site.uuid: site}))
    assert (site.uuid, "light-one") not in coordinator._pending_controls
    assert confirmed.sites[site.uuid].controls["light-one"].desired["Status"] == "ON"
    coordinator._pending_controls[("missing-site", "missing-control")] = {"Status": "OFF"}
    coordinator._apply_pending_controls(PoolsideData({site.uuid: site}))
    await coordinator.async_shutdown()


async def test_refresh_syncs_active_body_only_from_unambiguous_flow_control(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """A body mode follows a single confirmed Filter state, never equipment."""
    discovered = discover_sites(user_config).sites["site-alpha"]
    pool = BodyOfWater("pool", "Pool", "Pool", discovered.uuid)
    spa = BodyOfWater(
        "spa",
        "Spa",
        "Spa",
        discovered.uuid,
        {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}},
    )
    filter_control = replace(
        discovered.controls["filter-one"],
        raw={"BodyOfWater": pool.uuid, "Type": "Filter"},
        desired={"Status": "OFF"},
    )
    spa_filter = replace(
        filter_control,
        uuid="spa-filter",
        raw={"BodyOfWater": spa.uuid, "Type": "Filter"},
        desired={"Status": "ON"},
    )
    pump = replace(
        filter_control,
        uuid="pump-like-control",
        type="Pump",
        raw={"BodyOfWater": pool.uuid, "Type": "Pump"},
        desired={"Status": "ON"},
    )
    site = replace(
        discovered,
        bodies_of_water={pool.uuid: pool, spa.uuid: spa},
        controls={
            filter_control.uuid: filter_control,
            spa_filter.uuid: spa_filter,
            pump.uuid: pump,
        },
    )
    coordinator = PoolsideCoordinator(
        hass,
        config_entry,
        LoadClient(PoolsideData({site.uuid: site})),  # type: ignore[arg-type]
    )

    await coordinator._async_update_data()
    assert coordinator.active_body(site.uuid, "pool|spa") == spa.uuid

    ambiguous = replace(filter_control, desired={"Status": "ON"})
    coordinator._sync_confirmed_body_modes(
        PoolsideData(
            {site.uuid: replace(site, controls={**site.controls, ambiguous.uuid: ambiguous})}
        )
    )
    assert coordinator.active_body(site.uuid, "pool|spa") is None
    coordinator._active_bodies[(site.uuid, "pool|spa")] = spa.uuid
    coordinator._sync_confirmed_body_modes(
        PoolsideData({site.uuid: replace(site, controls={filter_control.uuid: filter_control})})
    )
    assert coordinator.active_body(site.uuid, "pool|spa") == spa.uuid
    await coordinator.async_shutdown()


async def test_flow_switch_waits_for_confirmation_without_hiding_body_controls(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """A mode procedure does not make independently safe entities disappear."""
    discovered = discover_sites(user_config).sites["site-alpha"]
    pool = BodyOfWater("pool", "Pool", "Pool", discovered.uuid)
    spa = BodyOfWater(
        "spa",
        "Spa",
        "Spa",
        discovered.uuid,
        {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}},
    )
    site = replace(
        discovered,
        bodies_of_water={"pool": pool, "spa": spa},
        flow_procedure={
            "FlowBasedProcedures": [{"FlowUUID": "flow", "FlatFlowAndPumpSpeeds": [{}]}],
            "ControlBasedProcedures": [{"FlowUUID": "flow", "Procedures": []}],
        },
    )
    client = LoadClient(PoolsideData({site.uuid: site}))
    client.async_run_flow_switch = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    coordinator._flow_transitions = {(site.uuid, "pool|spa"): {"state": "Stopping circulation"}}
    coordinator._active_bodies[(site.uuid, "pool|spa")] = "pool"
    assert coordinator.body_is_visible(site.uuid, "pool")
    coordinator._flow_transitions = None  # type: ignore[assignment]
    coordinator._active_bodies = None  # type: ignore[assignment]
    coordinator.set_active_body(site.uuid, "pool", "pool|spa")
    coordinator._active_bodies[(site.uuid, "pool|spa")] = "pool"
    coordinator.async_refresh = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda: coordinator._active_bodies.__setitem__((site.uuid, "pool|spa"), "spa")
    )
    await coordinator.async_run_flow_switch(site.uuid, "pool|spa", "spa")
    client.async_run_flow_switch.assert_awaited_once_with(site, "spa")  # type: ignore[attr-defined]
    assert coordinator.flow_transition(site.uuid, "pool|spa") is None


async def test_cross_body_control_activation_requires_confirmed_flow(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """Activation fails closed across bodies while Off and setpoints remain writable."""
    site = _route_site(user_config)
    client = BatchClient(PoolsideData({site.uuid: site}))
    client.async_set_control = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]
    group_key = coordinator.body_group_key(site.uuid, "pool")

    coordinator.set_active_body(site.uuid, "spa", group_key)
    with pytest.raises(PoolsideError, match="Confirm the body-flow change"):
        await coordinator.async_set_control(site.uuid, "filter-one", {"Status": "ON"})
    client.async_set_control.assert_not_awaited()  # type: ignore[attr-defined]

    await coordinator.async_set_control(site.uuid, "filter-one", {"PowerLevel": 42})
    coordinator.set_active_body(site.uuid, "pool", group_key)
    await coordinator.async_set_control(site.uuid, "filter-one", {"Status": "ON"})
    assert client.async_set_control.await_count == 2  # type: ignore[attr-defined]


async def test_light_group_batches_only_discovered_lights_and_reconciles(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """Aggregate writes batch real light Controls and reject mixed equipment targets."""
    site = discover_sites(user_config).sites["site-alpha"]
    client = BatchClient(PoolsideData({site.uuid: site}))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    await coordinator.async_set_light_group(
        site.uuid,
        ("light-combined", "light-one"),
        {"Status": "OFF"},
    )
    assert client.batches == [
        {
            "light-combined": {"Status": "OFF"},
            "light-one": {"Status": "OFF"},
        }
    ]
    coordinator.async_request_refresh.assert_awaited_once()

    with pytest.raises(ValueError, match="non-light"):
        await coordinator.async_set_light_group(
            site.uuid,
            ("light-one", "filter-one"),
            {"Status": "ON"},
        )

    rejecting_client = BatchClient(PoolsideData({site.uuid: site}), write_result=False)
    rejecting = PoolsideCoordinator(hass, config_entry, rejecting_client)  # type: ignore[arg-type]
    rejecting.data = PoolsideData({site.uuid: site})
    with pytest.raises(PoolsideError, match="rejected"):
        await rejecting.async_set_light_group(
            site.uuid,
            ("light-one",),
            {"Status": "ON"},
        )


async def test_flow_switch_rejection_and_invalid_group_fail_closed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """Rejected procedures and unknown bodies never change the confirmed mode."""
    discovered = discover_sites(user_config).sites["site-alpha"]
    pool = BodyOfWater("pool", "Pool", "Pool", discovered.uuid)
    spa = BodyOfWater(
        "spa",
        "Spa",
        "Spa",
        discovered.uuid,
        {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}},
    )
    site = replace(discovered, bodies_of_water={"pool": pool, "spa": spa})
    client = LoadClient(PoolsideData({site.uuid: site}))
    client.async_run_flow_switch = AsyncMock(return_value=False)  # type: ignore[attr-defined]
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    with pytest.raises(ValueError, match="flow group"):
        await coordinator.async_run_flow_switch(site.uuid, "pool|spa", "unknown")
    with pytest.raises(PoolsideError):
        await coordinator.async_run_flow_switch(site.uuid, "pool|spa", "spa")
    assert coordinator.active_body(site.uuid, "pool|spa") is None
    await coordinator.async_shutdown()


async def test_flow_switch_fails_when_cloud_confirms_a_different_body(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """A conflicting cloud snapshot never becomes an optimistic HA state."""
    discovered = discover_sites(user_config).sites["site-alpha"]
    pool = BodyOfWater("pool", "Pool", "Pool", discovered.uuid)
    spa = BodyOfWater(
        "spa",
        "Spa",
        "Spa",
        discovered.uuid,
        {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}},
    )
    site = replace(discovered, bodies_of_water={"pool": pool, "spa": spa})
    client = LoadClient(PoolsideData({site.uuid: site}))
    client.async_run_flow_switch = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    coordinator._active_bodies[(site.uuid, "pool|spa")] = "pool"
    coordinator.async_refresh = AsyncMock()  # type: ignore[method-assign]
    with pytest.raises(PoolsideError, match="confirm"):
        await coordinator.async_run_flow_switch(site.uuid, "pool|spa", "spa")
    assert coordinator.active_body(site.uuid, "pool|spa") == "pool"
    await coordinator.async_shutdown()


async def test_controller_derived_routes_batch_controls_without_hardware_writes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """A feature route changes sibling Controls in one controller-proven batch."""
    site = _route_site(user_config)
    client = BatchClient(PoolsideData({site.uuid: site}))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    group_key = coordinator.body_group_key(site.uuid, "pool")
    route = site.route_groups[0]
    coordinator.set_active_body(site.uuid, "pool", group_key)
    coordinator.async_request_refresh = AsyncMock()  # type: ignore[method-assign]

    assert coordinator.route_selection(site.uuid, route.key) == "spillover-control"
    coordinator.set_route_selection(site.uuid, route.key, "bubbler-control")
    await coordinator.async_set_route_enabled(site.uuid, route.key, enabled=True)
    assert client.batches == [
        {
            "bubbler-control": {"Status": "ON"},
            "spillover-control": {"Status": "OFF"},
        }
    ]
    coordinator.set_route_selection(site.uuid, route.key, None)
    await coordinator.async_set_route_enabled(site.uuid, route.key, enabled=False)
    assert client.batches[-1] == {
        "bubbler-control": {"Status": "OFF"},
        "spillover-control": {"Status": "OFF"},
    }

    coordinator.set_active_body(site.uuid, "spa", group_key)
    with pytest.raises(PoolsideError, match="confirmed water-flow"):
        await coordinator.async_set_route_enabled(site.uuid, route.key, enabled=True)
    assert len(client.batches) == 2
    with pytest.raises(ValueError, match="not available"):
        coordinator.set_route_selection(site.uuid, "missing-route", None)
    with pytest.raises(ValueError, match="not part"):
        coordinator.set_route_selection(site.uuid, route.key, "missing-control")
    await coordinator.async_shutdown()


async def test_group_shutdown_is_one_safe_batch_and_requires_cloud_confirmation(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """The dashboard Off action targets only high-level water Controls."""
    site = _route_site(user_config)
    client = BatchClient(PoolsideData({site.uuid: site}))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    group_key = coordinator.body_group_key(site.uuid, "pool")
    coordinator.set_active_body(site.uuid, "pool", group_key)

    async def confirmed_refresh() -> None:
        coordinator._active_bodies[(site.uuid, group_key)] = None

    coordinator.async_request_refresh = confirmed_refresh  # type: ignore[method-assign]
    await coordinator.async_turn_off_flow_group(site.uuid, group_key)
    assert client.batches == [
        {
            "filter-one": {"Status": "OFF"},
            "spillover-control": {"Status": "OFF"},
        }
    ]
    assert "light-one" not in client.batches[0]
    assert coordinator.dashboard_context(site.uuid, group_key) is None

    coordinator.set_active_body(site.uuid, "pool", group_key)
    rejecting = BatchClient(PoolsideData({site.uuid: site}), write_result=False)
    coordinator.client = rejecting  # type: ignore[assignment]
    with pytest.raises(PoolsideError, match="rejected"):
        await coordinator.async_turn_off_flow_group(site.uuid, group_key)
    assert coordinator.active_body(site.uuid, group_key) == "pool"
    await coordinator.async_shutdown()


async def test_route_and_shutdown_validation_fail_closed_for_incomplete_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_config: dict[str, Any],
) -> None:
    """Invalid graph keys, unavailable Controls, and stale flow state remain non-writable."""
    site = _route_site(user_config)
    client = BatchClient(PoolsideData({site.uuid: site}))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    coordinator.data = PoolsideData({site.uuid: site})
    route = site.route_groups[0]
    group_key = coordinator.body_group_key(site.uuid, "pool")
    assert coordinator.body_group_key(site.uuid, "missing-body") == "missing-body"
    with pytest.raises(ValueError, match="not available"):
        coordinator.set_dashboard_context(site.uuid, "missing-group", None)
    with pytest.raises(ValueError, match="not part"):
        coordinator.set_dashboard_context(site.uuid, group_key, "missing-body")
    with pytest.raises(ValueError, match="not available"):
        coordinator.route_selection(site.uuid, "missing-route")
    with pytest.raises(ValueError, match="not available"):
        await coordinator.async_set_route_enabled(site.uuid, "missing-route", enabled=True)
    with pytest.raises(ValueError, match="not available"):
        await coordinator.async_turn_off_flow_group(site.uuid, "missing-group")

    coordinator._route_selections.clear()
    off_controls = {
        key: replace(control, desired={"Status": "OFF"}) for key, control in site.controls.items()
    }
    coordinator.data = PoolsideData({site.uuid: replace(site, controls=off_controls)})
    assert coordinator.route_selection(site.uuid, route.key) == "bubbler-control"
    on_controls = {
        key: replace(control, desired={"Status": "ON"})
        for key, control in coordinator.site(site.uuid).controls.items()
    }
    coordinator.data = PoolsideData({site.uuid: replace(site, controls=on_controls)})
    assert coordinator.route_selection(site.uuid, route.key) is None

    coordinator.set_active_body(site.uuid, "pool", group_key)
    coordinator.client = BatchClient(  # type: ignore[assignment]
        PoolsideData({site.uuid: coordinator.site(site.uuid)}), write_result=False
    )
    with pytest.raises(PoolsideError, match="feature-route"):
        await coordinator.async_set_route_enabled(site.uuid, route.key, enabled=True)

    restricted_controls = dict(coordinator.site(site.uuid).controls)
    restricted_controls["filter-one"] = replace(
        restricted_controls["filter-one"], desired={"Status": "ON", "Restricted": True}
    )
    coordinator.data = PoolsideData({site.uuid: replace(site, controls=restricted_controls)})
    with pytest.raises(PoolsideError, match="restricted"):
        await coordinator.async_turn_off_flow_group(site.uuid, group_key)

    coordinator.data = PoolsideData({site.uuid: replace(site, controls=off_controls)})
    coordinator.set_active_body(site.uuid, "pool", group_key)
    with pytest.raises(PoolsideError, match="confirm water flow is off"):
        await coordinator.async_turn_off_flow_group(site.uuid, group_key)
    await coordinator.async_shutdown()


async def test_update_logs_safe_http_failure_metadata(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """Refresh diagnostics expose status metadata without response contents."""
    failure = CannotConnectError("synthetic", status=502, content_type="text/html")
    coordinator = PoolsideCoordinator(hass, config_entry, LoadClient(failure))  # type: ignore[arg-type]
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert "poolside_refresh outcome=failed" in caplog.text
    assert "status=502" in caplog.text
    assert "content_type=text/html" in caplog.text
    await coordinator.async_shutdown()


async def test_heartbeat_success_and_retryable_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeats call ping and keep retryable failures out of reauthentication."""

    async def stop_after_wait(
        awaitable: Coroutine[Any, Any, Any],
        *,
        timeout: float,  # noqa: ASYNC109
    ) -> None:
        del timeout
        awaitable.close()
        coordinator._stopping.set()
        raise TimeoutError

    monkeypatch.setattr("custom_components.poolside.coordinator.asyncio.wait_for", stop_after_wait)
    client = HeartbeatClient()
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1

    client = HeartbeatClient(CannotConnectError("synthetic"))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1

    client = HeartbeatClient(ProtocolError("synthetic"))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1

    client = HeartbeatClient()
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]

    async def stop_after_ping() -> bool:
        coordinator._stopping.set()
        return True

    client.async_ping = stop_after_ping  # type: ignore[method-assign]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 0


async def test_heartbeat_authentication_failure_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """An expired heartbeat token starts HA reauthentication and stops the loop."""
    client = HeartbeatClient(AuthenticationError("expired"))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    reauth = Mock()
    config_entry.async_start_reauth = reauth
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1
    reauth.assert_called_once_with(hass)


async def test_push_reconnect_refresh_ignore_reauth_and_idempotent_start(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Push refreshes relevant events, backs off failures, and reauthenticates once."""
    client = PushClient()
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    refresh = AsyncMock()
    reauth = Mock()
    monkeypatch.setattr(coordinator, "async_request_refresh", refresh)
    monkeypatch.setattr(config_entry, "async_start_reauth", reauth)

    async def instant_timeout(
        awaitable: Coroutine[Any, Any, Any],
        *,
        timeout: float,  # noqa: ASYNC109
    ) -> None:
        del timeout
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("custom_components.poolside.coordinator.asyncio.wait_for", instant_timeout)
    await coordinator._async_push_loop()
    refresh.assert_awaited_once()
    reauth.assert_called_once_with(hass)
    assert client.calls == 3

    coordinator._stopping.set()
    coordinator.start_push()
    task = coordinator._push_task
    heartbeat_task = coordinator._heartbeat_task
    coordinator.start_push()
    assert coordinator._push_task is task
    assert coordinator._heartbeat_task is heartbeat_task
    await coordinator.async_shutdown()
    await coordinator.async_shutdown()

    stopped = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    stopped._stopping.set()
    await stopped._async_push_loop()

    ending = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]

    async def stop_during_stream() -> AsyncIterator[tuple[str, dict[str, Any]]]:
        ending._stopping.set()
        if ending._stopping.is_set():
            return
        yield "unreachable", {}

    monkeypatch.setattr(client, "async_push_messages", stop_during_stream)
    await ending._async_push_loop()
