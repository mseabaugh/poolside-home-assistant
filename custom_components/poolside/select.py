"""Site-level Poolside Theme selector."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from . import PoolsideConfigEntry
from .const import DOMAIN
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .models import RouteGroup
from .redact import fingerprint


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up one dynamically updated Theme selector per site."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideEntity]:
    """Build dashboard-context, route, and Theme selectors from each site."""
    for site in coordinator.data.sites.values():
        groups = sorted(site.body_connection_groups, key=lambda group: tuple(sorted(group)))
        for index, group in enumerate(groups):
            yield PoolsideActiveBodySelect(coordinator, site.uuid, group, primary=index == 0)
        for route_group in site.route_groups:
            yield PoolsideRouteSelect(coordinator, site.uuid, route_group)
        if site.themes:
            yield PoolsideThemeSelect(coordinator, site.uuid)


class PoolsideActiveBodySelect(PoolsideEntity, SelectEntity):
    """Select dashboard context; confirmed flow remains controller-owned."""

    _attr_name = "Dashboard body"

    def __init__(
        self,
        coordinator: PoolsideCoordinator,
        site_uuid: str,
        group: frozenset[str] | None = None,
        *,
        primary: bool = False,
    ) -> None:
        """Initialize the local selector for one site."""
        super().__init__(coordinator, site_uuid)
        self._body_group: frozenset[str] = group or next(
            iter(
                sorted(
                    coordinator.site(site_uuid).body_connection_groups,
                    key=lambda item: tuple(sorted(item)),
                )
            )
        )
        self.group_key = "|".join(sorted(self._body_group))
        self._attr_unique_id = (
            f"{site_uuid}_active_body" if primary else f"{site_uuid}_active_body_{self.group_key}"
        )
        self._attr_name = "Dashboard body" if primary else "Dashboard body · " + self._group_label

    @property
    def _group_label(self) -> str:
        """Return a concise label for a disconnected body group."""
        site = self.coordinator.site(self.site_uuid)
        return " / ".join(site.bodies_of_water[uuid].name for uuid in sorted(self._body_group))

    @property
    def device_info(self) -> DeviceInfo:
        """Attach connected selectors to a dedicated flow-group device.

        A singleton group is the disconnected-body case and stays on that
        body's device.  Multi-body groups represent shared plumbing and must
        not appear to be owned by one particular body.
        """
        if len(self._body_group) == 1:
            body_uuid = next(iter(self._body_group))
            site = self.coordinator.site(self.site_uuid)
            body = site.bodies_of_water[body_uuid]
            return DeviceInfo(
                identifiers={(DOMAIN, f"{site.uuid}_{body.uuid}")},
                manufacturer="Poolside Tech",
                model="Body of Water",
                name=body.name,
                via_device=(DOMAIN, site.uuid),
            )
        site = self.coordinator.site(self.site_uuid)
        return DeviceInfo(
            identifiers={(DOMAIN, f"{site.uuid}_body_group_{self.group_key}")},
            manufacturer="Poolside Tech",
            model="Body Group",
            name=f"{self._group_label} Flow Group",
            via_device=(DOMAIN, site.uuid),
        )

    @property
    def _options_map(self) -> dict[str, str | None]:
        """Return stable labels mapped to discovered body identifiers."""
        site = self.coordinator.site(self.site_uuid)
        options: dict[str, str | None] = {"Off": None}
        counts = Counter(body.name for body in site.bodies_of_water.values())
        seen: Counter[str] = Counter()
        for body in site.bodies_of_water.values():
            if body.uuid not in self._body_group:
                continue
            seen[body.name] += 1
            label = body.name
            if counts[body.name] > 1:
                label = f"{body.name} ({seen[body.name]})"
            options[label] = body.uuid
        return options

    @property
    def options(self) -> list[str]:
        """Return the Off option and discovered body names."""
        return list(self._options_map)

    @property
    def current_option(self) -> str:
        """Return the dashboard body context, defaulting to Off."""
        selected = self.coordinator.dashboard_context(self.site_uuid, self.group_key)
        for label, body_uuid in self._options_map.items():
            if body_uuid == selected:
                return label
        return "Off"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose confirmed flow separately from the dashboard view."""
        transition = self.coordinator.flow_transition(self.site_uuid, self.group_key)
        confirmed = self.coordinator.active_body(self.site_uuid, self.group_key)
        confirmed_option = next(
            (label for label, body_uuid in self._options_map.items() if body_uuid == confirmed),
            "Off",
        )
        if transition is None:
            return {
                "confirmed_water_flow": confirmed_option,
                "flow_procedure_available": self.coordinator.site(
                    self.site_uuid
                ).flow_procedure_complete,
                "flow_procedure_reason": self.coordinator.site(
                    self.site_uuid
                ).flow_procedure_reason,
            }
        return {
            "confirmed_water_flow": confirmed_option,
            "flow_procedure_available": True,
            "transition_state": transition["state"],
            **transition,
        }

    @property
    def available(self) -> bool:
        """Dashboard context does not require a writable flow procedure."""
        return super().available

    async def async_select_option(self, option: str) -> None:
        """Select context or safely turn off discovered water-flow Controls."""
        if option not in self._options_map:
            raise ValueError("Body option is not available")
        target = self._options_map[option]
        current = self.current_option
        if option == current:
            return
        if target is None:
            await self.coordinator.async_turn_off_flow_group(self.site_uuid, self.group_key)
        else:
            self.coordinator.set_dashboard_context(self.site_uuid, self.group_key, target)


class PoolsideRouteSelect(PoolsideEntity, SelectEntity):
    """Select a controller-derived water-feature route without direct hardware writes."""

    _attr_name = "Water feature route"

    def __init__(
        self, coordinator: PoolsideCoordinator, site_uuid: str, route_group: RouteGroup
    ) -> None:
        """Initialize from one validated route group."""
        super().__init__(coordinator, site_uuid, route_group.body_uuid)
        self.route_group = route_group
        self._attr_unique_id = f"{route_group.key}_route"
        body = coordinator.site(site_uuid).bodies_of_water[route_group.body_uuid]
        self._attr_name = f"{body.name} water feature route"

    @property
    def _options_map(self) -> dict[str, str | None]:
        """Map user labels to discovered Control identifiers."""
        site = self.coordinator.site(self.site_uuid)
        counts = Counter(site.all_controls[uuid].name for uuid in self.route_group.control_uuids)
        seen: Counter[str] = Counter()
        options: dict[str, str | None] = {}
        for control_uuid in self.route_group.control_uuids:
            name = site.all_controls[control_uuid].name
            seen[name] += 1
            options[f"{name} ({seen[name]})" if counts[name] > 1 else name] = control_uuid
        options["Blend"] = None
        return options

    @property
    def options(self) -> list[str]:
        """Return discovered routes plus the controller-valid Blend option."""
        return list(self._options_map)

    @property
    def current_option(self) -> str:
        """Return the selected route label or Blend."""
        selected = self.coordinator.route_selection(self.site_uuid, self.route_group.key)
        return next(
            (
                label
                for label, control_uuid in self._options_map.items()
                if control_uuid == selected
            ),
            "Blend",
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose safe, display-only topology facts without remote identifiers."""
        return {
            "route_count": len(self.route_group.control_uuids),
            "controller_derived": True,
            "supports_blend": True,
            "poolside_route_group": fingerprint(self.route_group.key)[:12],
        }

    async def async_select_option(self, option: str) -> None:
        """Change only the route view used by the paired route switch."""
        if option not in self._options_map:
            raise ValueError("Route option is not available")
        self.coordinator.set_route_selection(
            self.site_uuid, self.route_group.key, self._options_map[option]
        )


def _theme_options(coordinator: PoolsideCoordinator, site_uuid: str) -> dict[str, str]:
    """Create human-readable unique options without exposing remote identifiers."""
    themes = list(coordinator.site(site_uuid).themes.values())
    counts = Counter(theme.name for theme in themes)
    seen: Counter[str] = Counter()
    options: dict[str, str] = {}
    for theme in themes:
        seen[theme.name] += 1
        option = theme.name
        if counts[theme.name] > 1:
            option = f"{theme.name} ({seen[theme.name]})"
        options[option] = theme.uuid
    return options


class PoolsideThemeSelect(PoolsideEntity, SelectEntity):
    """Activate one of a site's discovered Themes."""

    _attr_name = "Theme"

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str) -> None:
        """Initialize from a stable site UUID."""
        super().__init__(coordinator, site_uuid)
        self._attr_unique_id = f"{site_uuid}_theme"

    @property
    def _options_map(self) -> dict[str, str]:
        """Return the latest option-to-Theme mapping."""
        return _theme_options(self.coordinator, self.site_uuid)

    @property
    def options(self) -> list[str]:
        """Return dynamically discovered Theme names."""
        return list(self._options_map)

    @property
    def current_option(self) -> str | None:
        """Return a Theme explicitly marked active, if supplied by Poolside."""
        themes = self.coordinator.site(self.site_uuid).themes
        for option, theme_uuid in self._options_map.items():
            if themes[theme_uuid].raw.get("isWorking") is True:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        """Activate the selected discovered Theme."""
        theme_uuid = self._options_map.get(option)
        if theme_uuid is None:
            raise ValueError("Theme option is not available")
        await self.async_activate_theme(theme_uuid)
