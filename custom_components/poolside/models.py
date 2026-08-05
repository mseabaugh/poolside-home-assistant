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
    def disabled_reasons(self) -> tuple[str, ...]:
        """Return opaque disable reasons without interpreting them as writable targets."""
        value = self.desired.get("DisabledReasons", self.raw.get("DisabledReasons", []))
        if not isinstance(value, list):
            return ()
        return tuple(str(item) for item in value)

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
    def water_body_uuid(self) -> str | None:
        """Return the associated pool/spa body identifier when provided."""
        value = self.raw.get("BodyOfWater")
        return value if isinstance(value, str) and value else None

    @property
    def supports_percentage(self) -> bool:
        """Return whether this Control exposes a safe high-level percentage."""
        return any(
            key in self.raw or key in self.desired for key in ("PowerLevel", "PowerLevelIncrements")
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
class Site:
    """A complete discovered site snapshot."""

    uuid: str
    name: str
    controls: Mapping[str, Control] = field(default_factory=dict)
    combined_controls: Mapping[str, Control] = field(default_factory=dict)
    themes: Mapping[str, Theme] = field(default_factory=dict)
    equipment: Mapping[str, Equipment] = field(default_factory=dict)
    schedule_document: Mapping[str, Any] = field(default_factory=dict)
    alerts: tuple[Mapping[str, Any], ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

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
        for key in ("EquipmentItems", "Equipment", "Devices", "HardwareDevices"):
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
        sites.append(
            Site(
                uuid=site_uuid,
                name=site_name,
                controls=_index_unique(controls, lambda item: item.uuid, "Controls"),
                combined_controls=_index_unique(
                    combined, lambda item: item.uuid, "Combined Controls"
                ),
                themes=_index_unique(themes, lambda item: item.uuid, "Themes"),
                equipment=_index_unique(equipment, lambda item: item.uuid, "equipment"),
                schedule_document=schedule_document,
                raw=dict(site_raw),
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
        try:
            entity_uuid = _required_identifier(row, "state")
        except ProtocolError:
            continue
        key_value = row.get("item", row.get("name", row.get("StateName")))
        if isinstance(key_value, str) and "state" in row:
            state_by_entity.setdefault(entity_uuid, {})[key_value] = parse_state(row["state"])
        else:
            state_by_entity.setdefault(entity_uuid, {}).update(
                {
                    str(key): parse_state(value)
                    for key, value in row.items()
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
