"""Unit coverage for discovery, runtime state, and safety classification."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from custom_components.poolside.exceptions import (
    ProtocolError,
    RestrictedControlError,
    UnsafeWriteError,
)
from custom_components.poolside.models import (
    BodyOfWater,
    Control,
    ObjectKind,
    Site,
    _endpoint_uuids,
    _flows_for_control,
    _paths_for_flow,
    _route_groups,
    _string_values,
    apply_runtime,
    discover_sites,
    find_flow_document,
)
from custom_components.poolside.safety import SafetyPolicy

pytestmark = pytest.mark.unit


def test_find_flow_document_handles_nested_documents_and_non_mappings() -> None:
    """Flow metadata is found only in explicit nested config documents."""
    document = {"records": [{"data": {"FlowBasedProcedures": [], "extra": True}}]}
    assert find_flow_document(document)["extra"] is True
    assert find_flow_document(["ignored", {"ControlBasedProcedures": []}])
    assert find_flow_document({"records": ["ignored"]}) == {}


def test_route_parser_rejects_malformed_or_single_member_metadata() -> None:
    """A partial graph cannot accidentally become a writeable water-feature route."""
    control = Control(
        "feature-control",
        "Feature",
        "WaterFeature",
        "synthetic-site",
        raw={
            "BodyOfWater": "synthetic-pool",
            "ControlGroupUUID": "feature-group",
            "WaterFeature": True,
        },
    )
    controls = {control.uuid: control}
    assert _string_values(42) == set()
    assert _endpoint_uuids("not-an-endpoint") == set()
    assert _flows_for_control(
        controls,
        [None, {}, {"FlowUUID": 1}, {"FlowUUID": "feature-flow", "Procedures": control.uuid}],
    ) == {control.uuid: {"feature-flow"}}
    assert (
        _paths_for_flow(
            [
                None,
                {},
                {"FlowUUID": "feature-flow"},
                {"FlowUUID": "feature-flow", "FlatFlowAndPumpSpeeds": [None, {}]},
            ]
        )
        == {}
    )
    assert (
        _route_groups(
            controls,
            {
                "ControlBasedProcedures": [
                    {"FlowUUID": "feature-flow", "Procedures": [control.uuid]}
                ],
                "FlowBasedProcedures": [
                    {
                        "FlowUUID": "feature-flow",
                        "FlatFlowAndPumpSpeeds": [
                            {
                                "FlatFlow": {
                                    "Pump": "feature-pump",
                                    "Return": [{"UUID": "feature-return"}],
                                }
                            }
                        ],
                    }
                ],
            },
        )
        == ()
    )


def test_flow_procedure_requires_the_verified_poolside_shape(
    user_config: dict[str, object],
) -> None:
    """Only a FlowUUID/procedure document enables server-side body switching."""
    site = discover_sites(user_config).sites["site-alpha"]
    assert site.controller_uuid == "controller-one"
    assert replace(
        site, equipment={}, raw={"ControllerUUID": "controller-raw"}
    ).controller_uuid == ("controller-raw")
    assert site.flow_procedure_reason is not None
    assert "flow group" in site.flow_procedure_reason
    pool = BodyOfWater("pool", "Pool", "Pool", site.uuid)
    spa = BodyOfWater(
        "spa", "Spa", "Spa", site.uuid, {"Spillover": {"ConnectedThings": [{"UUID": "pool"}]}}
    )
    incomplete = replace(site, bodies_of_water={pool.uuid: pool, spa.uuid: spa})
    assert not incomplete.flow_procedure_complete
    assert incomplete.flow_procedure_reason is not None
    assert "metadata" in incomplete.flow_procedure_reason
    complete = replace(
        incomplete,
        flow_procedure={
            "FlowBasedProcedures": [
                {"FlowUUID": "flow", "CurrentPosition": 0, "FlatFlowAndPumpSpeeds": [{}]}
            ],
            "ControlBasedProcedures": [{"FlowUUID": "flow", "Procedures": []}],
        },
    )
    assert complete.flow_procedure_complete
    assert complete.flow_procedure_reason is None
    paired_without_optional_rows = replace(
        incomplete,
        flow_procedure={
            "FlowBasedProcedures": [{"FlowUUID": "flow"}],
            "ControlBasedProcedures": [{"FlowUUID": "flow"}],
        },
    )
    assert paired_without_optional_rows.flow_procedure_complete
    assert paired_without_optional_rows.flow_procedure_reason is None

    malformed = replace(
        incomplete,
        flow_procedure={
            "FlowBasedProcedures": [{"FlowUUID": "flow"}],
            "ControlBasedProcedures": [{"FlowUUID": "different-flow"}],
        },
    )
    assert not malformed.flow_procedure_complete
    assert malformed.flow_procedure_reason == "Poolside flow-procedure metadata is incomplete"


def test_discovery_and_runtime_merge(
    user_config: dict[str, object],
    states_payload: dict[str, object],
    desired_payload: dict[str, object],
) -> None:
    """Dynamic discovery preserves raw fields and merges typed runtime state."""
    data = discover_sites({"result": json.dumps(user_config)})
    assert not data.empty
    site = data.sites["site-alpha"]
    assert site.name == "Synthetic Pool"
    assert site.raw["FutureSiteField"] == {"preserved": True}
    assert site.schedule_document["FutureField"] == {"preserved": True}
    assert site.combined_controls["light-combined"].kind is ObjectKind.COMBINED_CONTROL
    assert site.controls["light-one"].available_effects == ("Blue", "Green", "America")
    assert site.controls["filter-one"].supports_percentage
    assert not site.controls["heat-one"].supports_percentage

    merged = apply_runtime(site, states_payload, desired_payload)
    assert merged.equipment["pump-one"].states == {
        "RPM": 1800,
        "Online": True,
        "Version": "004",
    }
    assert merged.equipment["controller-one"].states == {
        "Online": False,
        "Firmware": "1.2.3",
    }
    assert merged.controls["light-one"].desired["Brightness"] == 65
    assert merged.controls["jets-restricted"].restricted
    assert not merged.controls["jets-restricted"].available
    assert merged.controls["jets-restricted"].disabled_reasons == ("synthetic-reason",)
    assert not merged.controls["heat-one"].is_light
    assert merged.controls["heat-one"].supports_temperature_setpoint
    assert not merged.controls["filter-one"].is_blower


def test_runtime_merge_accepts_installer_style_equipment_telemetry(
    user_config: dict[str, object],
) -> None:
    """Installer/runtime rows can expose RPM as read-only equipment state."""
    site = discover_sites(user_config).sites["site-alpha"]
    merged = apply_runtime(
        site,
        {"states": [{"item": "pump-one", "name": "RPM", "state": "2850"}]},
        {},
    )
    assert merged.equipment["pump-one"].states["RPM"] == 2850


def test_body_relationships_only_join_explicitly_connected_bodies(
    user_config: dict[str, object],
) -> None:
    """Spillover and cross-body Combined Controls define XOR; unrelated bodies do not."""
    payload = deepcopy(user_config)
    site = cast("dict[str, object]", cast("list[object]", payload["Sites"])[0])
    site["BodiesOfWater"] = [
        {"UUID": "pool", "Name": "Pool", "Type": "Pool"},
        {
            "UUID": "spa",
            "Name": "Spa",
            "Type": "Spa",
            "Spillover": {
                "ConnectedThings": [
                    {"UUID": "pool"},
                    "pool",
                    {"UUID": ""},
                    {"UUID": "pool"},
                    {"UUID": "ghost"},
                ]
            },
        },
        {"UUID": "pond", "Name": "Pond", "Type": "Pond", "Spillover": {"ConnectedThings": {}}},
    ]
    site["Controls"] = [
        {"UUID": "pool-light", "Name": "Pool Light", "Type": "Light", "BodyOfWater": "pool"},
        {"UUID": "spa-light", "Name": "Spa Light", "Type": "Light", "BodyOfWater": "spa"},
        {"UUID": "pond-light", "Name": "Pond Light", "Type": "Light", "BodyOfWater": "pond"},
        {"UUID": "ghost-control", "Name": "Ghost", "Type": "Light", "BodyOfWater": "ghost"},
    ]
    site["CombinedControls"] = [
        {
            "UUID": "pool-spa-combined",
            "Name": "Pool and Spa",
            "Type": "Combined",
            "Controls": [{"ControlUUID": "pool-light"}, {"ControlUUID": "spa-light"}],
        }
    ]
    cast("list[dict[str, object]]", site["CombinedControls"]).append(
        {
            "UUID": "invalid-members",
            "Name": "Invalid members",
            "Type": "Combined",
            "Controls": [
                "bad",
                {"ControlUUID": "missing"},
                {"ControlUUID": "pond-light"},
                {"ControlUUID": "ghost-control"},
            ],
        }
    )
    discovered = discover_sites(payload).sites["site-alpha"]
    groups = {frozenset(group) for group in discovered.body_connection_groups}
    assert frozenset({"pool", "spa"}) in groups
    assert frozenset({"pond"}) in groups


def test_route_groups_require_a_complete_controller_derived_feature_path() -> None:
    """Feature routes need shared Controls, one pump, and an actuator endpoint."""
    site_uuid = "synthetic-site"
    body = BodyOfWater("synthetic-pool", "Pool", "Pool", site_uuid)
    spillover = Control(
        "spillover-control",
        "Feature Spillover",
        "WaterFeature",
        site_uuid,
        desired={"Status": "OFF", "PowerLevel": 50},
        raw={
            "BodyOfWater": body.uuid,
            "ControlGroupUUID": "feature-group",
            "WaterFeature": True,
            "PowerLevelIncrements": [0, 50, 100],
        },
    )
    bubbler = replace(
        spillover,
        uuid="bubbler-control",
        name="Bubbler",
        desired={"Status": "ON", "PowerLevel": 75},
    )
    document = {
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
    }
    site = Site(
        site_uuid,
        "Synthetic",
        controls={spillover.uuid: spillover, bubbler.uuid: bubbler},
        bodies_of_water={body.uuid: body},
        flow_procedure=document,
    )

    assert not replace(spillover, raw={"BodyOfWater": body.uuid}).supports_percentage
    assert spillover.supports_percentage
    assert spillover.is_water_flow_control
    assert len(site.route_groups) == 1
    route = site.route_groups[0]
    assert route.body_uuid == body.uuid
    assert route.control_uuids == (bubbler.uuid, spillover.uuid)
    assert route.pump_uuid == "feature-pump"
    assert route.actuator_uuids == ("feature-return",)
    assert site.route_group_for_control(spillover.uuid) == route
    assert site.route_group_for_control("missing") is None

    no_endpoint = replace(
        site,
        flow_procedure={
            **document,
            "FlowBasedProcedures": [
                {
                    "FlowUUID": "feature-flow",
                    "FlatFlowAndPumpSpeeds": [{"FlatFlow": {"Pump": "feature-pump"}}],
                }
            ],
        },
    )
    ambiguous_pump = replace(
        site,
        flow_procedure={
            **document,
            "FlowBasedProcedures": [
                {
                    "FlowUUID": "feature-flow",
                    "FlatFlowAndPumpSpeeds": [
                        {"FlatFlow": {"Pump": "pump-a", "Return": [{"UUID": "return-a"}]}},
                        {"FlatFlow": {"Pump": "pump-b", "Return": [{"UUID": "return-b"}]}},
                    ],
                }
            ],
        },
    )
    assert no_endpoint.route_groups == ()
    assert ambiguous_pump.route_groups == ()


def test_discovery_accepts_mapping_collections_and_root_site(
    user_config: dict[str, object],
) -> None:
    """Config shape variants remain discoverable without site-specific assumptions."""
    site = deepcopy(user_config["Sites"][0])  # type: ignore[index]
    site["controls"] = {row["UUID"]: row for row in site.pop("Controls")}
    site["combinedControls"] = site.pop("CombinedControls")
    site["themes"] = site.pop("Themes")
    site["schedule"] = []
    site.pop("Schedule")
    root = discover_sites(site)
    assert tuple(root.sites) == ("site-alpha",)
    assert root.sites["site-alpha"].schedule_document == {}

    wrapped = discover_sites({"site": site})
    assert tuple(wrapped.sites) == ("site-alpha",)
    assert discover_sites({"Sites": []}).empty


def test_discovery_accepts_mobile_config_document_array() -> None:
    """The mobile API's persisted-document array is normalized safely."""
    payload = {
        "result": [
            {"data": [{"ignored": True}]},
            {
                "siteId": 42,
                "data": {
                    "Location": {"UUID": "mobile-site", "Name": "Synthetic Mobile Site"},
                    "BodiesOfWater": [{"UUID": "body-1"}],
                    "Controls": [{"UUID": "mobile-control", "Name": "Pump", "Type": "Pump"}],
                    "CombinedControls": [],
                    "Devices": [{"UUID": "mobile-device", "Name": "Device", "DeviceType": "Pump"}],
                    "FutureField": {"preserved": True},
                },
            },
            {"data": {"Schedule": [{"ItemUUID": "mobile-control"}]}},
        ],
    }
    site = discover_sites(payload).sites["mobile-site"]
    assert site.name == "Synthetic Mobile Site"
    assert site.remote_id == 42
    assert tuple(site.controls) == ("mobile-control",)
    assert tuple(site.equipment) == ("mobile-device",)
    assert site.schedule_document == {"Schedule": [{"ItemUUID": "mobile-control"}]}
    assert site.raw["FutureField"] == {"preserved": True}


def test_mobile_config_array_preserves_explicit_site_without_optional_documents() -> None:
    """A minimal mobile document remains valid when optional records are absent."""
    site = discover_sites(
        [{"data": {"UUID": "explicit-site", "Controls": [{"UUID": "control"}]}}]
    ).sites["explicit-site"]
    assert site.name == "Poolside"
    assert site.schedule_document == {}


def test_discovery_fallback_names_types_and_equipment_sources() -> None:
    """Missing display metadata uses safe local fallbacks while identifiers remain required."""
    payload = {
        "Site": {
            "siteId": "fallback-site",
            "Controls": [{"uuid": "control-a"}],
            "CombinedControls": [{"ControlUUID": "combined-a"}],
            "Themes": [{"uuid": "theme-a"}],
            "Equipment": [{"entityUuid": "equipment-a"}],
            "Devices": [{"deviceUuid": "equipment-b", "type": "Pump"}],
            "HardwareDevices": [{"UUID": "equipment-c", "DeviceType": "Controller"}],
        }
    }
    site = discover_sites(payload).sites["fallback-site"]
    assert site.name == "Poolside"
    assert site.controls["control-a"].name == "Control"
    assert site.controls["control-a"].type == "Control"
    assert site.combined_controls["combined-a"].type == "CombinedControl"
    assert site.themes["theme-a"].name == "Theme"
    assert set(site.equipment) == {"equipment-a", "equipment-b", "equipment-c"}


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"Sites": [{"Name": "Missing ID"}]},
        {"Sites": [{"UUID": "same"}, {"UUID": "same"}]},
        {
            "Sites": [
                {
                    "UUID": "site",
                    "Controls": [{"UUID": "same"}, {"UUID": "same"}],
                }
            ]
        },
    ],
)
def test_discovery_rejects_unsafe_ambiguity(payload: object) -> None:
    """Malformed and duplicate identifiers fail instead of weakening classification."""
    with pytest.raises(ProtocolError):
        discover_sites(payload)


def test_runtime_shape_variants_and_missing_rows(user_config: dict[str, object]) -> None:
    """Runtime parsing handles mappings, wrappers, malformed rows, and retained prior values."""
    site = discover_sites(user_config).sites["site-alpha"]
    first = apply_runtime(
        site,
        {"result": {"states": {"UUID": "pump-one", "RPM": "900"}}},
        {"result": {"ControlUUID": "filter-one", "Status": "OFF"}},
    )
    assert first.equipment["pump-one"].states["RPM"] == 900
    assert first.controls["filter-one"].desired["Status"] == "OFF"

    second = apply_runtime(first, "bad", {"DesiredStates": "bad"})
    assert second.equipment["pump-one"].states["RPM"] == 900
    assert second.controls["filter-one"].desired["Status"] == "OFF"


def test_control_properties_with_non_list_values(user_config: dict[str, object]) -> None:
    """Unexpected optional capability and restriction values remain conservative."""
    site = discover_sites(user_config).sites["site-alpha"]
    control = site.controls["light-one"]
    raw = dict(control.raw)
    raw["AvailableColors"] = "Blue"
    raw["AvailableShows"] = [1, {"Name": 2}, "Blue", "Blue"]
    desired = {"DisabledReasons": "unexpected"}
    changed = control.__class__(
        uuid=control.uuid,
        name=control.name,
        type=control.type,
        site_uuid=control.site_uuid,
        kind=control.kind,
        desired=desired,
        raw=raw,
    )
    assert changed.available_effects == ("Blue",)
    assert changed.disabled_reasons == ()


def test_control_classification_uses_discovery_schema_not_runtime_fields(
    user_config: dict[str, object], desired_payload: dict[str, object]
) -> None:
    """Generic runtime light fields do not turn heaters into lights."""
    site = apply_runtime(discover_sites(user_config).sites["site-alpha"], {}, desired_payload)
    heating = site.controls["heat-one"]
    assert not heating.is_light
    assert heating.is_heating
    assert tuple(site.heating_controls) == ("heat-one",)
    light = site.controls["light-one"]
    assert light.is_light
    assert replace(light, desired={"DisabledReasons": ["interlock"]}).available


def test_safety_policy_authorizes_only_confirmed_targets_and_fields(
    user_config: dict[str, object], desired_payload: dict[str, object]
) -> None:
    """Controls and Themes pass; equipment, restrictions, and unknown schemas fail."""
    site = apply_runtime(
        discover_sites(user_config).sites["site-alpha"],
        {},
        desired_payload,
    )
    policy = SafetyPolicy()
    assert policy.authorize_control(site, "filter-one", {"Status": "ON"}).uuid == "filter-one"
    assert policy.authorize_control(site, "light-one", {"LightName": "Blue"}).is_light
    assert policy.authorize_theme(site, "theme-calm", "ON").name == "Calm"

    with pytest.raises(UnsafeWriteError, match="not a discovered Control"):
        policy.authorize_control(site, "pump-one", {"Status": "ON"})
    with pytest.raises(RestrictedControlError):
        policy.authorize_control(site, "jets-restricted", {"Status": "ON"})
    installer = replace(site.controls["filter-one"], raw={"Type": "Filter", "InstallerMode": True})
    installer_site = replace(site, controls={**site.controls, "filter-one": installer})
    assert installer.installer_only
    assert not installer.available
    with pytest.raises(RestrictedControlError):
        policy.authorize_control(installer_site, "filter-one", {"Status": "ON"})
    with pytest.raises(UnsafeWriteError, match="unconfirmed field"):
        policy.authorize_control(site, "filter-one", {})
    with pytest.raises(UnsafeWriteError, match="unconfirmed field"):
        policy.authorize_control(site, "filter-one", {"DesiredRPM": 3000})
    with pytest.raises(UnsafeWriteError, match="unconfirmed field"):
        policy.authorize_control(site, "filter-one", {"Brightness": 50})
    with pytest.raises(UnsafeWriteError, match="not a discovered Theme"):
        policy.authorize_theme(site, "unknown", "ON")
    with pytest.raises(UnsafeWriteError, match="deactivation"):
        policy.authorize_theme(site, "theme-calm", "OFF")
