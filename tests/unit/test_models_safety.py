"""Unit coverage for discovery, runtime state, and safety classification."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from custom_components.poolside.exceptions import (
    ProtocolError,
    RestrictedControlError,
    UnsafeWriteError,
)
from custom_components.poolside.models import (
    ObjectKind,
    apply_runtime,
    discover_sites,
)
from custom_components.poolside.safety import SafetyPolicy

pytestmark = pytest.mark.unit


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
    assert merged.controls["jets-restricted"].disabled_reasons == ("synthetic-reason",)
    assert not merged.controls["heat-one"].is_light


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
