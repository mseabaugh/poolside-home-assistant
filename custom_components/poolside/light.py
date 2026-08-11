"""Native Home Assistant lights backed by safe Poolside light Controls."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode, LightEntityFeature
from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .coordinator import PoolsideCoordinator
from .entity import PoolsideEntity, setup_dynamic_entities
from .light_codec import (
    decode_rgb,
    encode_rgb,
    ha_brightness_to_poolside,
    poolside_brightness_to_ha,
)
from .models import Control


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PoolsideConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up dynamically discovered Poolside light Controls."""
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(
        setup_dynamic_entities(
            coordinator,
            async_add_entities,
            lambda: _entities(coordinator),
            lambda entity: entity.unique_id or "",
        )
    )


def _entities(coordinator: PoolsideCoordinator) -> Iterable[PoolsideLight | PoolsideAllLights]:
    """Build one aggregate plus every ordinary or Combined light Control."""
    for site in coordinator.data.sites.values():
        light_uuids = tuple(
            sorted(
                control.uuid
                for control in site.all_controls.values()
                if control.available and control.is_light
            )
        )
        if light_uuids:
            yield PoolsideAllLights(coordinator, site.uuid)
        for control in site.all_controls.values():
            if control.available and control.is_light:
                yield PoolsideLight(coordinator, site.uuid, control.uuid)


class PoolsideAllLights(PoolsideEntity, LightEntity):
    """One native aggregate for all discovered light Controls at a Poolside site."""

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str) -> None:
        """Initialize with a site-scoped stable identifier."""
        super().__init__(coordinator, site_uuid)
        self._attr_unique_id = f"{site_uuid}_all_lights"
        self._attr_name = "All lights"
        self._attr_icon = "mdi:lightbulb-group"
        self._attr_supported_color_modes = {ColorMode.RGB}

    @property
    def _controls(self) -> tuple[Control, ...]:
        """Return the latest available light Controls in stable order."""
        return tuple(
            sorted(
                (
                    control
                    for control in self.coordinator.site(self.site_uuid).all_controls.values()
                    if control.available and control.is_light
                ),
                key=lambda control: control.uuid,
            )
        )

    @property
    def available(self) -> bool:
        """Require coordinator availability and at least one discovered light."""
        return bool(super().available and self._controls)

    @property
    def is_on(self) -> bool:
        """Report on when any Poolside light is on."""
        return any(
            str(control.desired.get("Status", "OFF")).upper() == "ON" for control in self._controls
        )

    @property
    def color_mode(self) -> ColorMode:
        """Expose RGB because every member is an RGB Poolside light."""
        return ColorMode.RGB

    @property
    def brightness(self) -> int | None:
        """Use the brightest valid member, matching Home Assistant group behavior."""
        values: list[int] = []
        for control in self._controls:
            value = control.desired.get("Brightness")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            try:
                values.append(poolside_brightness_to_ha(value))
            except ValueError:
                continue
        return max(values) if values else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Expose a color only when all colored members agree."""
        colors = {
            color
            for control in self._controls
            if (color := decode_rgb(control.desired.get("Color", control.desired.get("LightName"))))
            is not None
        }
        return next(iter(colors)) if len(colors) == 1 else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Apply one authorized batch to all discovered light Controls."""
        changes: dict[str, object] = {"Status": "ON"}
        if ATTR_BRIGHTNESS in kwargs:
            changes["Brightness"] = ha_brightness_to_poolside(int(kwargs[ATTR_BRIGHTNESS]))
        if ATTR_RGB_COLOR in kwargs:
            encoded = encode_rgb(tuple(kwargs[ATTR_RGB_COLOR]))
            changes.update({"Color": encoded, "LightName": encoded})
        await self.coordinator.async_set_light_group(
            self.site_uuid, tuple(control.uuid for control in self._controls), changes
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn every discovered Poolside light off in one authorized batch."""
        await self.coordinator.async_set_light_group(
            self.site_uuid,
            tuple(control.uuid for control in self._controls),
            {"Status": "OFF"},
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose safe aggregate counts and a human-readable brightness percentage."""
        brightness = self.brightness
        return {
            **super().extra_state_attributes,
            "light_count": len(self._controls),
            "lights_on": sum(
                str(control.desired.get("Status", "OFF")).upper() == "ON"
                for control in self._controls
            ),
            "brightness_percent": round(brightness * 100 / 255) if brightness is not None else None,
        }


class PoolsideLight(PoolsideEntity, LightEntity):
    """A discovered Poolside light Control."""

    def __init__(self, coordinator: PoolsideCoordinator, site_uuid: str, control_uuid: str) -> None:
        """Initialize from stable remote identifiers."""
        control = coordinator.site(site_uuid).all_controls[control_uuid]
        super().__init__(coordinator, site_uuid, control.water_body_uuid)
        self.control_uuid = control_uuid
        self._attr_unique_id = control_uuid
        self._attr_name = control.name
        self._attr_supported_color_modes = {ColorMode.RGB}
        if control.available_effects:
            self._attr_supported_features = LightEntityFeature.EFFECT

    @property
    def _control(self) -> Control:
        """Return the latest immutable Control."""
        return self.coordinator.site(self.site_uuid).all_controls[self.control_uuid]

    @property
    def is_on(self) -> bool:
        """Return desired light power state."""
        return str(self._control.desired.get("Status", "OFF")).upper() == "ON"

    @property
    def color_mode(self) -> ColorMode:
        """Expose the richest confirmed light mode."""
        return ColorMode.RGB

    @property
    def brightness(self) -> int | None:
        """Return Poolside brightness on Home Assistant's scale."""
        value = self._control.desired.get("Brightness")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        try:
            return poolside_brightness_to_ha(value)
        except ValueError:
            return None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return an arbitrary RGB color when the confirmed encoding is present."""
        value = self._control.desired.get("Color", self._control.desired.get("LightName"))
        return decode_rgb(value)

    @property
    def effect(self) -> str | None:
        """Return a discovered named color/show when selected."""
        value = self._control.desired.get("LightName")
        return value if isinstance(value, str) and value in self.effect_list else None

    @property
    def effect_list(self) -> list[str]:
        """Return dynamically discovered named colors and shows."""
        return list(self._control.available_effects)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Apply one validated light-state mutation."""
        changes: dict[str, object] = {"Status": "ON"}
        if ATTR_BRIGHTNESS in kwargs:
            changes["Brightness"] = ha_brightness_to_poolside(int(kwargs[ATTR_BRIGHTNESS]))
        if ATTR_RGB_COLOR in kwargs:
            encoded = encode_rgb(tuple(kwargs[ATTR_RGB_COLOR]))
            changes.update({"Color": encoded, "LightName": encoded})
        if ATTR_EFFECT in kwargs:
            effect = str(kwargs[ATTR_EFFECT])
            if effect not in self.effect_list:
                raise ValueError("Effect is not available for this Control")
            changes.update({"Color": effect, "LightName": effect})
        await self.async_write_control(self.control_uuid, changes)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off through the high-level Control API."""
        await self.async_write_control(self.control_uuid, {"Status": "OFF"})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose only non-sensitive high-level inconsistency state."""
        return {
            **super().extra_state_attributes,
            "inconsistent_combined_control": bool(
                self._control.desired.get("InconsistentCombinedControl", False)
            ),
        }
