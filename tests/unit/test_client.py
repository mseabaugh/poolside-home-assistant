"""Unit coverage for typed client operations and safe write payloads."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from custom_components.poolside.client import PoolsideClient
from custom_components.poolside.exceptions import ProtocolError, UnsafeWriteError
from custom_components.poolside.models import BodyOfWater, apply_runtime, discover_sites
from tests.fakes import FakeTransport

pytestmark = pytest.mark.unit


def _responses(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build typed-client response fixtures."""
    return {
        "Site.getDesiredState": desired_payload,
        "Site.getStates": states_payload,
        "Site.getAllConfig": {},
        "Site.setDesiredState2": True,
        "Site.setTheme": True,
        "User.getConfig": user_config,
        "ping": True,
    }


async def test_read_validation_and_multi_site_load(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Typed reads, validation, concurrent runtime loads, and fingerprints work together."""
    second = dict(user_config["Sites"][0])
    second["UUID"] = "site-beta"
    second["Name"] = "Second Site"
    second["Controls"] = []
    second["CombinedControls"] = []
    second["Themes"] = []
    second["EquipmentItems"] = []
    second["Schedule"] = {}
    config = {"Sites": [user_config["Sites"][0], second]}
    transport = FakeTransport(_responses(config, states_payload, desired_payload))
    client = PoolsideClient(transport)

    assert await client.async_ping()
    assert len(await client.async_validate()) == 64
    data = await client.async_load()
    assert set(data.sites) == {"site-alpha", "site-beta"}
    assert data.sites["site-alpha"].equipment["pump-one"].states["RPM"] == 1800
    assert await client.async_get_states("site-alpha") == states_payload
    assert await client.async_get_desired_state("site-alpha") == desired_payload
    assert await client.async_get_config() == config
    assert ("User.getConfig", {}) in transport.calls


async def test_high_level_read_commands_are_read_only() -> None:
    """Maintenance/configuration reads are exposed without any write path."""
    transport = FakeTransport(
        {
            "Site.getAllConfig": {"config": True},
            "Site.getAlerts": {"alerts": []},
            "Site.getWeather": {"weather": True},
        }
    )
    client = PoolsideClient(transport)
    assert await client.async_get_all_config("site-alpha") == {"config": True}
    assert await client.async_get_alerts("site-alpha") == {"alerts": []}
    assert await client.async_get_weather("site-alpha") == {"weather": True}
    assert all(method.startswith("Site.get") for method, _ in transport.calls)


async def test_validation_rejects_false_ping_and_empty_account() -> None:
    """A non-true ping and an account without sites fail validation."""
    false_ping = PoolsideClient(FakeTransport({"ping": False}))
    with pytest.raises(ProtocolError, match="ping"):
        await false_ping.async_ping()

    empty = PoolsideClient(FakeTransport({"ping": True, "User.getConfig": {"Sites": []}}))
    with pytest.raises(ProtocolError, match="did not contain"):
        await empty.async_validate()
    assert (await empty.async_load()).empty


async def test_safe_control_and_theme_writes(
    user_config: dict[str, Any],
    desired_payload: dict[str, Any],
) -> None:
    """Writes preserve full desired records and never bypass the safety policy."""
    transport = FakeTransport({"Site.setDesiredState2": True, "Site.setTheme": {"accepted": True}})
    client = PoolsideClient(transport)
    site = apply_runtime(
        discover_sites(user_config).sites["site-alpha"],
        {},
        desired_payload,
    )
    assert await client.async_set_control(site, "light-one", {"Brightness": 50}) is True
    method, params = transport.calls[-1]
    assert method == "Site.setDesiredState2"
    assert params is not None
    record = params["DesiredStates"][0]
    assert record["ControlUUID"] == "light-one"
    assert record["Brightness"] == 50
    assert record["LightName"] == "Blue"
    assert params["SiteUUID"] == "site-alpha"
    assert isinstance(params["BatchUUID"], str)

    assert await client.async_activate_theme(site, "theme-calm") == {"accepted": True}
    assert transport.calls[-1] == (
        "Site.setTheme",
        {"Status": "ON", "UUID": "theme-calm", "siteUuid": "site-alpha"},
    )
    with pytest.raises(UnsafeWriteError):
        await client.async_set_control(site, "pump-one", {"Status": "ON"})


async def test_write_builds_minimum_record_when_desired_state_is_missing(
    user_config: dict[str, Any],
) -> None:
    """A discovered Control without runtime state still receives an identified full record."""
    transport = FakeTransport({"Site.setDesiredState2": True})
    client = PoolsideClient(transport)
    site = discover_sites(user_config).sites["site-alpha"]
    await client.async_set_control(site, "filter-one", {"Status": "ON"})
    params = transport.calls[-1][1]
    assert params is not None
    assert params["DesiredStates"] == [{"ControlUUID": "filter-one", "Status": "ON"}]
    assert params["SiteUUID"] == "site-alpha"


async def test_authorized_control_batches_are_atomic_and_reauthorize_every_member(
    user_config: dict[str, Any], desired_payload: dict[str, Any]
) -> None:
    """Route and shutdown batches preserve every desired record in one RPC."""
    transport = FakeTransport({"Site.setDesiredState2": True})
    client = PoolsideClient(transport)
    site = apply_runtime(discover_sites(user_config).sites["site-alpha"], {}, desired_payload)

    assert (
        await client.async_set_controls(
            site,
            {
                "filter-one": {"Status": "OFF"},
                "light-one": {"Brightness": 40},
            },
        )
        is True
    )
    method, params = transport.calls[-1]
    assert method == "Site.setDesiredState2"
    assert params is not None
    assert [record["ControlUUID"] for record in params["DesiredStates"]] == [
        "filter-one",
        "light-one",
    ]
    assert params["DesiredStates"][0]["Status"] == "OFF"
    assert params["DesiredStates"][1]["LightName"] == "Blue"
    before = len(transport.calls)
    assert await client.async_set_controls(site, {}) is True
    assert len(transport.calls) == before
    with pytest.raises(UnsafeWriteError):
        await client.async_set_controls(
            site,
            {"filter-one": {"Status": "OFF"}, "pump-one": {"Status": "ON"}},
        )
    assert len(transport.calls) == before


async def test_flow_switch_uses_one_attendant_procedure_write(
    user_config: dict[str, Any],
) -> None:
    """Body switching never expands into raw filter, valve, or pump writes."""
    transport = FakeTransport({"Site.runFlowSwitchProcedure": True})
    client = PoolsideClient(transport)
    site = discover_sites(user_config).sites["site-alpha"]
    site = replace(
        site,
        bodies_of_water={
            "pool": BodyOfWater("pool", "Pool", "Pool", site.uuid),
            "spa": BodyOfWater(
                "spa",
                "Spa",
                "Spa",
                site.uuid,
                {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}},
            ),
        },
        flow_procedure={
            "FlowBasedProcedures": [{"FlowUUID": "flow", "FlatFlowAndPumpSpeeds": [{}]}],
            "ControlBasedProcedures": [{"FlowUUID": "flow", "Procedures": []}],
        },
    )
    assert await client.async_run_flow_switch(site, "spa") is True
    method, params = transport.calls[-1]
    assert method == "Site.runFlowSwitchProcedure"
    assert params == {
        "siteId": "site-alpha",
        "BodyOfWaterUUID": "spa",
    }
    assert all("setDesiredState" not in call[0] for call in transport.calls)


async def test_flow_switch_fails_closed_without_procedure(user_config: dict[str, Any]) -> None:
    """A site without complete flow metadata cannot issue a mode write."""
    client = PoolsideClient(FakeTransport({"Site.runFlowSwitchProcedure": True}))
    site = discover_sites(user_config).sites["site-alpha"]
    with pytest.raises(ProtocolError, match="flow procedure"):
        await client.async_run_flow_switch(site, None)


async def test_flow_switch_rejects_unknown_body_and_unverified_off_procedure(
    user_config: dict[str, Any],
) -> None:
    """Flow writes reject identifiers that are not discovered or not routable."""
    transport = FakeTransport({"Site.runFlowSwitchProcedure": True})
    client = PoolsideClient(transport)
    site = discover_sites(user_config).sites["site-alpha"]
    site = replace(
        site,
        bodies_of_water={"pool": BodyOfWater("pool", "Pool", "Pool", site.uuid)},
        flow_procedure={
            "FlowBasedProcedures": [{"FlowUUID": "flow", "FlatFlowAndPumpSpeeds": [{}]}],
            "ControlBasedProcedures": [{"FlowUUID": "flow", "Procedures": []}],
        },
    )
    with pytest.raises(ProtocolError, match="not discovered"):
        await client.async_run_flow_switch(site, "unknown")
    with pytest.raises(ProtocolError, match="Off flow"):
        await client.async_run_flow_switch(site, None)


async def test_push_filtering_and_site_replacement(user_config: dict[str, Any]) -> None:
    """Pushes require method/params shapes and state replacement is immutable."""
    messages: list[dict[str, Any]] = [
        {"method": "Site.setStates", "params": {"siteId": "site-alpha"}},
        {"method": 1, "params": {}},
        {"method": "ignored", "params": []},
    ]
    client = PoolsideClient(FakeTransport(messages=messages))
    assert [item async for item in client.async_push_messages()] == [
        ("Site.setStates", {"siteId": "site-alpha"})
    ]

    data = discover_sites(user_config)
    site = data.sites["site-alpha"]
    replaced = client.replace_site(data, site)
    assert replaced is not data
    assert replaced.sites["site-alpha"] is site
