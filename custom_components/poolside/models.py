"""Typed, forward-compatible Poolside discovery and runtime models."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from .exceptions import ProtocolError
from .parser import decode_json_value, parse_state, require_mapping


class ObjectKind(StrEnum):
    """Safety-relevant Poolside object classification."""

    CONTROL = "control"
    COMBINED_CONTROL = "combined_control"
    THEME = "theme"
    EQUIPMENT = "equipment"


@dataclass(frozen=True, slots=True)
class BodyOfWater:
    """A discovered body of water and explicit service relationships."""

    uuid: str
    name: str
    type: str
    site_uuid: str
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def connected_body_uuids(self) -> tuple[str, ...]:
        """Return bodies explicitly connected by Poolside's Spillover graph."""
        spillover = self.raw.get("Spillover")
        if not isinstance(spillover, Mapping):
            return ()
        things = spillover.get("ConnectedThings")
        if not isinstance(things, list):
            return ()
        result: list[str] = []
        for thing in things:
            if isinstance(thing, Mapping):
                value = thing.get("UUID")
                if isinstance(value, str) and value and value not in result:
                    result.append(value)
        return tuple(result)


@dataclass(frozen=True, slots=True)
class Control:
    """A writable high-level Poolside Control."""

    uuid: str
    name: str
    type: str
    site_uuid: str
    kind: ObjectKind = ObjectKind.CONTROL
    desired: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def restricted(self) -> bool:
        """Return whether Poolside marks this Control restricted."""
        return bool(self.desired.get("Restricted", self.raw.get("Restricted", False)))

    @property
    def installer_only(self) -> bool:
        """Return whether Poolside marks a control as maintenance/installer-only."""
        markers = (
            "InstallerOnly",
            "InstallerMode",
            "MaintenanceOnly",
            "Calibration",
            "Commissioning",
        )
        return any(bool(self.raw.get(marker) or self.desired.get(marker)) for marker in markers)

    @property
    def disabled_reasons(self) -> tuple[str, ...]:
        """Return opaque disable reasons without interpreting them as writable targets."""
        value = self.desired.get("DisabledReasons", self.raw.get("DisabledReasons", []))
        if not isinstance(value, list):
            return ()
        return tuple(str(item) for item in value)

    @property
    def available(self) -> bool:
        """Return whether the service currently allows this control to appear."""
        # Poolside reuses DisabledReasons across generic desired-state rows;
        # light rows can inherit another feature's interlock reason. Keep the
        # discovered light visible, while authorize_control still fail-closes
        # any attempted write when the reason is present.
        return (
            not self.restricted
            and not self.installer_only
            and (self.is_light or not self.disabled_reasons)
        )

    @property
    def is_light(self) -> bool:
        """Return whether this is a discovered light Control."""
        # Runtime desired-state documents reuse generic fields (including
        # LightName/Brightness) for every control.  Classification must come
        # from the discovered control schema, never from desired telemetry.
        lowered = self.type.lower()
        return "light" in lowered or isinstance(self.raw.get("Light"), Mapping)

    @property
    def is_heating(self) -> bool:
        """Return whether this is a discovered pool/spa heating Control."""
        return self.type.lower() in {"heating", "heater", "heatingcontrol"}

    @property
    def is_blower(self) -> bool:
        """Return whether this safe high-level Control is a variable-speed blower."""
        return "blower" in self.type.lower()

    @property
    def supports_temperature_setpoint(self) -> bool:
        """Return whether the discovered heating Control reports a SetPoint."""
        return self.is_heating and ("SetPoint" in self.raw or "SetPoint" in self.desired)

    @property
    def water_body_uuid(self) -> str | None:
        """Return the associated pool/spa body identifier when provided."""
        value = self.raw.get("BodyOfWater")
        return value if isinstance(value, str) and value else None

    @property
    def supports_percentage(self) -> bool:
        """Return whether this Control exposes a safe high-level percentage."""
        return any(key in self.raw for key in ("PowerLevel", "PowerLevelIncrements", "SpeedRange"))

    @property
    def is_water_feature(self) -> bool:
        """Return whether discovery, rather than runtime telemetry, marks a feature."""
        value = self.raw.get("WaterFeature")
        return bool(value) or "waterfeature" in self.type.lower().replace(" ", "")

    @property
    def is_water_flow_control(self) -> bool:
        """Return whether this high-level Control participates in water flow.

        This is only used to limit a bulk *off* request to discovered
        application-level Controls.  It never makes equipment writable.
        """
        lowered = self.type.lower()
        return not self.is_light and (
            self.is_heating
            or self.is_water_feature
            or any(
                token in lowered for token in ("blower", "cleaner", "filter", "jet", "spillover")
            )
        )

    @property
    def available_effects(self) -> tuple[str, ...]:
        """Return discovered named colors and shows."""
        effects: list[str] = []
        for key in ("AvailableColors", "AvailableShows"):
            values = self.raw.get(key, [])
            if isinstance(values, list):
                for value in values:
                    name = value.get("Name") if isinstance(value, Mapping) else value
                    if isinstance(name, str) and name not in effects:
                        effects.append(name)
        return tuple(effects)


@dataclass(frozen=True, slots=True)
class Theme:
    """A discovered Poolside Theme."""

    uuid: str
    name: str
    site_uuid: str
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Equipment:
    """A read-only physical Poolside equipment item."""

    uuid: str
    name: str
    type: str
    site_uuid: str
    states: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteGroup:
    """One controller-proven, multi-route water-feature group.

    A route group is deliberately derived only from Poolside identifiers.  The
    presentation labels of its Controls are never used to establish hydraulic
    relationships.
    """

    key: str
    body_uuid: str
    control_uuids: tuple[str, ...]
    flow_uuid: str
    pump_uuid: str
    actuator_uuids: tuple[str, ...]


def find_flow_document(value: Any) -> Mapping[str, Any]:
    """Find the explicit flow-procedure document without guessing relationships."""
    if isinstance(value, Mapping):
        if any(key in value for key in ("FlowBasedProcedures", "ControlBasedProcedures")):
            return value
        for child in value.values():
            found = find_flow_document(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_flow_document(child)
            if found:
                return found
    return {}


def _find_body_root(parent: dict[str, str], value: str) -> str:
    """Find one body component root with path compression."""
    while parent[value] != value:
        parent[value] = parent[parent[value]]
        value = parent[value]
    return value


def _union_body_roots(parent: dict[str, str], left: str, right: str) -> None:
    """Join two known body components."""
    if left not in parent or right not in parent:
        return
    left_root = _find_body_root(parent, left)
    right_root = _find_body_root(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def _body_connection_groups(
    bodies: Mapping[str, BodyOfWater],
    controls: Mapping[str, Control],
    combined_controls: Mapping[str, Control],
) -> tuple[frozenset[str], ...]:
    """Build explicit connected components without inferring from telemetry."""
    parent = {uuid: uuid for uuid in bodies}

    for body in bodies.values():
        for connected in body.connected_body_uuids:
            _union_body_roots(parent, body.uuid, connected)

    for combined in combined_controls.values():
        members = combined.raw.get("Controls", [])
        member_bodies: set[str] = set()
        for member in members:
            if not isinstance(member, Mapping):
                continue
            control_uuid = member.get("ControlUUID")
            if not isinstance(control_uuid, str) or control_uuid not in controls:
                continue
            body_uuid = controls[control_uuid].water_body_uuid
            if body_uuid in parent:
                member_bodies.add(body_uuid)
        for body_uuid in tuple(member_bodies)[1:]:
            _union_body_roots(parent, next(iter(member_bodies)), body_uuid)

    groups: dict[str, set[str]] = {}
    for uuid in parent:
        groups.setdefault(_find_body_root(parent, uuid), set()).add(uuid)
    return tuple(frozenset(group) for group in groups.values())


def _string_values(value: Any) -> set[str]:
    """Collect only string values from a documented nested procedure shape."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return set().union(*(_string_values(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_string_values(item) for item in value)) if value else set()
    return set()


def _endpoint_uuids(value: Any) -> set[str]:
    """Read explicit actuator identifiers from Return/Suction procedure rows."""
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key in ("UUID", "uuid", "ItemUUID", "ActuatorUUID"):
            item = value.get(key)
            if isinstance(item, str) and item:
                result.add(item)
        for item in value.values():
            result.update(_endpoint_uuids(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_endpoint_uuids(item))
    return result


_MIN_ROUTE_MEMBERS = 2


def _flows_for_control(
    controls: Mapping[str, Control], procedures: list[Any]
) -> dict[str, set[str]]:
    """Map a discovered Control to explicitly named flow procedures."""
    result: dict[str, set[str]] = {}
    for procedure in procedures:
        if not isinstance(procedure, Mapping):
            continue
        flow_uuid = procedure.get("FlowUUID")
        if not isinstance(flow_uuid, str) or not flow_uuid:
            continue
        for control_uuid in _string_values(procedure.get("Procedures")) & set(controls):
            result.setdefault(control_uuid, set()).add(flow_uuid)
    return result


def _paths_for_flow(procedures: list[Any]) -> dict[str, set[tuple[str, tuple[str, ...]]]]:
    """Map each flow procedure to its complete, explicit pump/actuator paths."""
    result: dict[str, set[tuple[str, tuple[str, ...]]]] = {}
    for procedure in procedures:
        if not isinstance(procedure, Mapping):
            continue
        flow_uuid = procedure.get("FlowUUID")
        rows = procedure.get("FlatFlowAndPumpSpeeds")
        if not isinstance(flow_uuid, str) or not flow_uuid or not isinstance(rows, list):
            continue
        for row in rows:
            flat_flow = row.get("FlatFlow") if isinstance(row, Mapping) else None
            if not isinstance(flat_flow, Mapping):
                continue
            pump_uuid = flat_flow.get("Pump")
            endpoints = _endpoint_uuids(flat_flow.get("Return")) | _endpoint_uuids(
                flat_flow.get("Suction")
            )
            if isinstance(pump_uuid, str) and pump_uuid and endpoints:
                result.setdefault(flow_uuid, set()).add((pump_uuid, tuple(sorted(endpoints))))
    return result


def _route_candidates(
    controls: Mapping[str, Control], flows_for_control: Mapping[str, set[str]]
) -> dict[tuple[str, str], list[Control]]:
    """Group feature Controls only when their configured group/body edges agree."""
    result: dict[tuple[str, str], list[Control]] = {}
    for control in controls.values():
        group_uuid = control.raw.get("ControlGroupUUID")
        if (
            isinstance(group_uuid, str)
            and group_uuid
            and control.water_body_uuid
            and control.is_water_feature
            and control.uuid in flows_for_control
        ):
            result.setdefault((group_uuid, control.water_body_uuid), []).append(control)
    return result


def _route_groups(
    controls: Mapping[str, Control], document: Mapping[str, Any]
) -> tuple[RouteGroup, ...]:
    """Derive multi-route feature groups from complete controller metadata.

    The graph requires a shared discovered ControlGroup, body, control-based
    flow procedure, one mapped pump, and at least one actuator endpoint.  A
    missing edge makes the candidate disappear instead of being guessed.
    """
    control_procedures = document.get("ControlBasedProcedures")
    flow_procedures = document.get("FlowBasedProcedures")
    if not isinstance(control_procedures, list) or not isinstance(flow_procedures, list):
        return ()

    flows_for_control = _flows_for_control(controls, control_procedures)
    paths_for_flow = _paths_for_flow(flow_procedures)
    candidates = _route_candidates(controls, flows_for_control)

    result: list[RouteGroup] = []
    for (control_group_uuid, body_uuid), members in candidates.items():
        if len(members) < _MIN_ROUTE_MEMBERS:
            continue
        shared_flows = set.intersection(*(flows_for_control[member.uuid] for member in members))
        for flow_uuid in sorted(shared_flows):
            paths = paths_for_flow.get(flow_uuid, set())
            if len(paths) != 1:
                continue
            pump_uuid, actuator_uuids = next(iter(paths))
            member_uuids = tuple(sorted(member.uuid for member in members))
            result.append(
                RouteGroup(
                    key=f"{body_uuid}|{control_group_uuid}|{flow_uuid}|{pump_uuid}",
                    body_uuid=body_uuid,
                    control_uuids=member_uuids,
                    flow_uuid=flow_uuid,
                    pump_uuid=pump_uuid,
                    actuator_uuids=actuator_uuids,
                )
            )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Site:
    """A complete discovered site snapshot."""

    uuid: str
    name: str
    controls: Mapping[str, Control] = field(default_factory=dict)
    bodies_of_water: Mapping[str, BodyOfWater] = field(default_factory=dict)
    combined_controls: Mapping[str, Control] = field(default_factory=dict)
    themes: Mapping[str, Theme] = field(default_factory=dict)
    equipment: Mapping[str, Equipment] = field(default_factory=dict)
    schedule_document: Mapping[str, Any] = field(default_factory=dict)
    alerts: tuple[Mapping[str, Any], ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
    flow_procedure: Mapping[str, Any] = field(default_factory=dict)

    @property
    def remote_id(self) -> str | int:
        """Return the API site identifier, falling back for legacy payloads."""
        value = self.raw.get("_poolside_site_id")
        return value if isinstance(value, (str, int)) else self.uuid

    @property
    def all_controls(self) -> dict[str, Control]:
        """Return ordinary and Combined Controls indexed together."""
        return {**self.controls, **self.combined_controls}

    @property
    def heating_controls(self) -> Mapping[str, Control]:
        """Return at most one heating control per pool/spa body."""
        result: dict[str, Control] = {}
        for control in self.all_controls.values():
            if not control.is_heating:
                continue
            key = control.water_body_uuid or control.uuid
            result.setdefault(key, control)
        return result

    @property
    def body_connection_groups(self) -> tuple[frozenset[str], ...]:
        """Return explicit XOR groups, keeping unrelated bodies separate."""
        return _body_connection_groups(
            self.bodies_of_water, self.all_controls, self.combined_controls
        )

    @property
    def route_groups(self) -> tuple[RouteGroup, ...]:
        """Return only controller-proven multi-route water-feature groups."""
        return _route_groups(self.all_controls, self.flow_procedure)

    def route_group_for_control(self, control_uuid: str) -> RouteGroup | None:
        """Return the discovered route group that owns one high-level Control."""
        return next(
            (group for group in self.route_groups if control_uuid in group.control_uuids), None
        )

    def flow_controls_for_group(self, group: frozenset[str]) -> tuple[Control, ...]:
        """Return writable high-level water controls in a connected body group."""
        return tuple(
            control
            for control in self.all_controls.values()
            if control.water_body_uuid in group and control.is_water_flow_control
        )

    @property
    def controller_uuid(self) -> str | None:
        """Return the discovered Attendant/controller UUID for flow RPCs."""
        for item in self.equipment.values():
            if "controller" in item.type.lower() or "attendant" in item.type.lower():
                return item.uuid
        value = self.raw.get("ControllerUUID", self.raw.get("controllerUuid"))
        return value if isinstance(value, str) and value else None

    @property
    def flow_procedure_complete(self) -> bool:
        """Require an explicitly paired server procedure before exposing a mode.

        HA delegates the complete pump and valve handoff to Poolside's cloud
        procedure.  It must not parse, reconstruct, or write those physical
        rows itself.  Requiring every optional diagnostic row made valid cloud
        procedures unavailable.  A matching pair of server-issued flow IDs is
        the capability proof; selecting a mode still invokes one cloud
        procedure and never a raw equipment write.
        """
        document = self.flow_procedure
        flows = document.get("FlowBasedProcedures")
        controls = document.get("ControlBasedProcedures")
        flow_uuids = (
            {
                flow["FlowUUID"]
                for flow in flows
                if isinstance(flow, Mapping)
                and isinstance(flow.get("FlowUUID"), str)
                and flow["FlowUUID"]
            }
            if isinstance(flows, list)
            else set()
        )
        control_uuids = (
            {
                control["FlowUUID"]
                for control in controls
                if isinstance(control, Mapping)
                and isinstance(control.get("FlowUUID"), str)
                and control["FlowUUID"]
            }
            if isinstance(controls, list)
            else set()
        )
        return bool(flow_uuids & control_uuids and self.body_connection_groups)

    @property
    def flow_procedure_reason(self) -> str | None:
        """Return a non-sensitive reason when safe mode selection is unavailable."""
        if self.flow_procedure_complete:
            return None
        if not self.body_connection_groups:
            return "Poolside has not reported a connected body-of-water flow group"
        if not self.flow_procedure:
            return "Poolside has not reported flow-procedure metadata"
        return "Poolside flow-procedure metadata is incomplete"


@dataclass(frozen=True, slots=True)
class PoolsideData:
    """Coordinator-owned state for every discovered site."""

    sites: Mapping[str, Site] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """Return whether discovery yielded no sites."""
        return not self.sites


def _mapping_list(mapping: Mapping[str, Any], *keys: str) -> list[Mapping[str, Any]]:
    """Read a case-variant collection while preserving unknown fields."""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return [item for item in value.values() if isinstance(item, Mapping)]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _required_identifier(raw: Mapping[str, Any], context: str) -> str:
    """Read an identifier used for safe classification."""
    for key in (
        "UUID",
        "uuid",
        "siteUuid",
        "siteId",
        "ControlUUID",
        "entityUuid",
        "deviceUuid",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    raise ProtocolError(f"Missing identifier for {context}")


def _display_name(raw: Mapping[str, Any], fallback: str) -> str:
    """Read a non-empty display name."""
    for key in ("Name", "name", "BodyOfWaterName"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _type_name(raw: Mapping[str, Any], fallback: str) -> str:
    """Read the most specific available object type."""
    for key in ("Type", "type", "ItemType", "DeviceType", "FeatureType"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def _index_unique[T](
    items: Iterable[T], identifier: Callable[[T], str], context: str
) -> dict[str, T]:
    """Index objects and reject duplicates that could weaken safety classification."""
    indexed: dict[str, T] = {}
    for item in items:
        item_id = identifier(item)
        if item_id in indexed:
            raise ProtocolError(f"Duplicate identifier in {context}")
        indexed[item_id] = item
    return indexed


def _unwrap_config(payload: Any) -> Mapping[str, Any]:
    """Normalize result wrappers and string-serialized configuration."""
    current = decode_json_value(payload)
    if isinstance(current, Mapping) and "result" in current:
        current = decode_json_value(current["result"])
    # The mobile API returns User.getConfig as a list of persisted documents.
    # The site document is the record containing BodiesOfWater/Controls; the
    # remaining records are independent telemetry, billing, and schedule
    # documents.  Fold only those documented fields into the site document and
    # retain every unknown field for forward compatibility.
    if isinstance(current, list):
        documents = [decode_json_value(item) for item in current]
        site_document = next(
            (
                item.get("data")
                for item in documents
                if isinstance(item, Mapping)
                and isinstance(item.get("data"), Mapping)
                and any(key in item["data"] for key in ("BodiesOfWater", "Controls"))
            ),
            None,
        )
        if isinstance(site_document, Mapping):
            site = dict(site_document)
            record = next(
                (
                    item
                    for item in documents
                    if isinstance(item, Mapping) and item.get("data") is site_document
                ),
                None,
            )
            if isinstance(record, Mapping) and isinstance(record.get("siteId"), (str, int)):
                site["_poolside_site_id"] = record["siteId"]
            location = site.get("Location")
            if isinstance(location, Mapping):
                site.setdefault("UUID", location.get("UUID"))
                site.setdefault("Name", location.get("Name"))
            schedule_document = next(
                (
                    item.get("data", {}).get("Schedule")
                    for item in documents
                    if isinstance(item, Mapping)
                    and isinstance(item.get("data"), Mapping)
                    and isinstance(item["data"].get("Schedule"), list)
                ),
                None,
            )
            if isinstance(schedule_document, list):
                site["Schedule"] = {"Schedule": schedule_document}
            return {"Sites": [site]}
    return require_mapping(current, "Poolside configuration")


def discover_sites(payload: Any) -> PoolsideData:
    """Discover sites and safety-relevant objects without hard-coded equipment lists."""
    root = _unwrap_config(payload)
    site_rows = _mapping_list(root, "Sites", "sites")
    if not site_rows:
        site_value = root.get("Site", root.get("site"))
        if isinstance(site_value, Mapping):
            site_rows = [site_value]
        elif any(
            key in root
            for key in (
                "Controls",
                "controls",
                "CombinedControls",
                "combinedControls",
                "SiteUUID",
                "siteUuid",
                "siteId",
            )
        ):
            site_rows = [root]

    sites: list[Site] = []
    for site_raw in site_rows:
        site_uuid = _required_identifier(site_raw, "site")
        site_name = _display_name(site_raw, "Poolside")

        controls = [
            Control(
                uuid=_required_identifier(raw, "Control"),
                name=_display_name(raw, "Control"),
                type=_type_name(raw, "Control"),
                site_uuid=site_uuid,
                raw=dict(raw),
            )
            for raw in _mapping_list(site_raw, "Controls", "controls")
        ]
        bodies = [
            BodyOfWater(
                uuid=_required_identifier(raw, "body of water"),
                name=_display_name(raw, "Body of water"),
                type=_type_name(raw, "BodyOfWater"),
                site_uuid=site_uuid,
                raw=dict(raw),
            )
            for raw in _mapping_list(site_raw, "BodiesOfWater", "bodiesOfWater")
        ]
        combined = [
            Control(
                uuid=_required_identifier(raw, "Combined Control"),
                name=_display_name(raw, "Combined Control"),
                type=_type_name(raw, "CombinedControl"),
                site_uuid=site_uuid,
                kind=ObjectKind.COMBINED_CONTROL,
                raw=dict(raw),
            )
            for raw in _mapping_list(site_raw, "CombinedControls", "combinedControls")
        ]
        themes = [
            Theme(
                uuid=_required_identifier(raw, "Theme"),
                name=_display_name(raw, "Theme"),
                site_uuid=site_uuid,
                raw=dict(raw),
            )
            for raw in _mapping_list(site_raw, "Themes", "themes")
        ]

        equipment_rows: list[Mapping[str, Any]] = []
        for key in (
            "EquipmentItems",
            "Equipment",
            "Devices",
            "HardwareDevices",
            "PhysicalDevices",
            "Hardware",
        ):
            equipment_rows.extend(_mapping_list(site_raw, key))
        equipment = [
            Equipment(
                uuid=_required_identifier(raw, "equipment"),
                name=_display_name(raw, "Equipment"),
                type=_type_name(raw, "Equipment"),
                site_uuid=site_uuid,
                raw=dict(raw),
            )
            for raw in equipment_rows
        ]

        schedule_value = site_raw.get("Schedule", site_raw.get("schedule", {}))
        schedule_document = dict(schedule_value) if isinstance(schedule_value, Mapping) else {}
        flow_procedure = find_flow_document(site_raw)
        sites.append(
            Site(
                uuid=site_uuid,
                name=site_name,
                controls=_index_unique(controls, lambda item: item.uuid, "Controls"),
                bodies_of_water=_index_unique(bodies, lambda item: item.uuid, "BodiesOfWater"),
                combined_controls=_index_unique(
                    combined, lambda item: item.uuid, "Combined Controls"
                ),
                themes=_index_unique(themes, lambda item: item.uuid, "Themes"),
                equipment=_index_unique(equipment, lambda item: item.uuid, "equipment"),
                schedule_document=schedule_document,
                raw=dict(site_raw),
                flow_procedure=dict(flow_procedure),
            )
        )

    return PoolsideData(_index_unique(sites, lambda item: item.uuid, "sites"))


def _runtime_rows(payload: Any, collection_key: str) -> list[Mapping[str, Any]]:
    """Normalize a runtime payload into state records."""
    current = decode_json_value(payload)
    if isinstance(current, Mapping) and "result" in current:
        current = decode_json_value(current["result"])
    if isinstance(current, Mapping):
        rows = current.get(collection_key, current.get(collection_key.lower(), current))
    else:
        rows = current
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, Mapping)]
    if isinstance(rows, Mapping):
        return [rows]
    return []


def apply_runtime(site: Site, states_payload: Any, desired_payload: Any) -> Site:
    """Merge runtime state into immutable discovered objects."""
    state_by_entity: dict[str, dict[str, Any]] = {}
    for row in _runtime_rows(states_payload, "states"):
        # Site.getStates uses `item` as the equipment UUID and `name` as the
        # telemetry key, while older responses use entityUuid/item.
        legacy_entity_uuid = row.get("item")
        normalized_row = row
        if (
            "entityUuid" not in row
            and isinstance(legacy_entity_uuid, str)
            and isinstance(row.get("name"), str)
        ):
            normalized_row = {**row, "entityUuid": legacy_entity_uuid, "item": row["name"]}
        try:
            entity_uuid = _required_identifier(normalized_row, "state")
        except ProtocolError:
            continue
        key_value = normalized_row.get(
            "item", normalized_row.get("name", normalized_row.get("StateName"))
        )
        if isinstance(key_value, str) and "state" in normalized_row:
            state_by_entity.setdefault(entity_uuid, {})[key_value] = parse_state(
                normalized_row["state"]
            )
        else:
            state_by_entity.setdefault(entity_uuid, {}).update(
                {
                    str(key): parse_state(value)
                    for key, value in normalized_row.items()
                    if key not in {"UUID", "uuid", "entityUuid", "siteUuid", "siteId"}
                }
            )

    desired_by_control: dict[str, Mapping[str, Any]] = {}
    for row in _runtime_rows(desired_payload, "DesiredStates"):
        try:
            control_uuid = _required_identifier(row, "desired state")
        except ProtocolError:
            continue
        desired_by_control[control_uuid] = dict(row)

    controls = {
        item_uuid: replace(control, desired=desired_by_control.get(item_uuid, control.desired))
        for item_uuid, control in site.controls.items()
    }
    combined = {
        item_uuid: replace(control, desired=desired_by_control.get(item_uuid, control.desired))
        for item_uuid, control in site.combined_controls.items()
    }
    equipment = {
        item_uuid: replace(item, states=state_by_entity.get(item_uuid, item.states))
        for item_uuid, item in site.equipment.items()
    }
    return replace(site, controls=controls, combined_controls=combined, equipment=equipment)
