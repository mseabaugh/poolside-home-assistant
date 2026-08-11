"""Safe high-level binary Poolside Controls."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .models import Control, RouteGroup
from .redact import fingerprint

_SAFE_TYPE_HINTS: Final = (
    "blower",
    "cleaner",
    "filter",
    "heat",
    "heater",
    "jet",
    "spillover",
    "waterfeature",
    "water feature",
)


def _safe_binary(control: Control) -> bool:
    """Classify only confirmed high-level non-light feature Controls."""
    lowered = control.type.lower()
    return not control.is_light and any(hint in lowered for hint in _SAFE_TYPE_HINTS)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up dynamically discovered safe Control switches."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideSwitch | PoolsideRouteSwitch]:
    """Build switches for allow-listed Control classifications."""
    for site in coordinator.data.sites.values():
        for control in site.all_controls.values():
            if (
                (control.available or control.is_heating)
                and _safe_binary(control)
                and not (control.is_blower and control.supports_percentage)
            ):
                yield PoolsideSwitch(coordinator, site.uuid, control.uuid)
        for route_group in site.route_groups:
            yield PoolsideRouteSwitch(coordinator, site.uuid, route_group)


class PoolsideSwitch(PoolsideEntity, SwitchEntity):
    """A safe discovered high-level binary Control."""

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, control_uuid: str) -> None:
        """Initialize from a stable Control UUID."""
        control = coordinator.site(site_uuid).all_controls[control_uuid]
        super().__init__(coordinator, site_uuid, control.water_body_uuid)
        self.control_uuid = control_uuid
        self._attr_unique_id = control_uuid
        self._attr_name = control.name

    @property
    def is_on(self) -> bool:
        """Return desired high-level Control status."""
        control = self.coordinator.site(self.site_uuid).all_controls[self.control_uuid]
        return str(control.desired.get("Status", "OFF")).upper() == "ON"

    @property
    def available(self) -> bool:
        """Hide an existing entity when Poolside no longer permits its control."""
        control = self.coordinator.site(self.site_uuid).all_controls.get(self.control_uuid)
        return bool(
            super().available
            and control is not None
            and control.available
            and _safe_binary(control)
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Mark route members without exposing Poolside identifiers to HA state."""
        route = self.coordinator.site(self.site_uuid).route_group_for_control(self.control_uuid)
        if route is None:
            return super().extra_state_attributes
        return {
            **super().extra_state_attributes,
            "poolside_route_group": fingerprint(route.key)[:12],
            "poolside_route_member": True,
        }

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on through the high-level Control API."""
        route = self.coordinator.site(self.site_uuid).route_group_for_control(self.control_uuid)
        if route is not None:
            self.coordinator.set_route_selection(self.site_uuid, route.key, self.control_uuid)
            await self.coordinator.async_set_route_enabled(self.site_uuid, route.key, enabled=True)
            return
        await self.async_write_control(self.control_uuid, {"Status": "ON"})

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off through the high-level Control API."""
        await self.async_write_control(self.control_uuid, {"Status": "OFF"})


class PoolsideRouteSwitch(PoolsideEntity, SwitchEntity):
    """One master switch for a controller-derived multi-route feature group."""

    def __init__(
        self, coordinator: PoolsideCoordinator, site_uuid: str, route_group: RouteGroup
    ) -> None:
        """Initialize from a complete controller-derived route group."""
        super().__init__(coordinator, site_uuid, route_group.body_uuid)
        self.route_group = route_group
        self._attr_unique_id = f"{route_group.key}_enabled"
        body = coordinator.site(site_uuid).bodies_of_water[route_group.body_uuid]
        self._attr_name = f"{body.name} water feature routes"

    @property
    def _selected_controls(self) -> tuple[str, ...]:
        """Return the selected member or all members for Blend."""
        selected = self.coordinator.route_selection(self.site_uuid, self.route_group.key)
        return self.route_group.control_uuids if selected is None else (selected,)

    @property
    def is_on(self) -> bool:
        """Return confirmed state for the current route selection."""
        controls = self.coordinator.site(self.site_uuid).all_controls
        return all(
            str(controls[control_uuid].desired.get("Status", "OFF")).upper() == "ON"
            for control_uuid in self._selected_controls
        )

    @property
    def available(self) -> bool:
        """Fail closed unless every route member and its body flow are confirmed."""
        site = self.coordinator.site(self.site_uuid)
        group_key = self.coordinator.body_group_key(self.site_uuid, self.route_group.body_uuid)
        return bool(
            super().available
            and self.coordinator.active_body(self.site_uuid, group_key)
            == self.route_group.body_uuid
            and all(
                control_uuid in site.all_controls and site.all_controls[control_uuid].available
                for control_uuid in self.route_group.control_uuids
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose safe cardinality rather than controller IDs or equipment rows."""
        return {
            **super().extra_state_attributes,
            "poolside_route_group": fingerprint(self.route_group.key)[:12],
            "poolside_control_kind": "route_group",
            "route_count": len(self.route_group.control_uuids),
            "supports_blend": True,
        }

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable the selected route through one authorized control batch."""
        await self.coordinator.async_set_route_enabled(
            self.site_uuid, self.route_group.key, enabled=True
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable every member of the selected route group in one batch."""
        await self.coordinator.async_set_route_enabled(
            self.site_uuid, self.route_group.key, enabled=False
        )
