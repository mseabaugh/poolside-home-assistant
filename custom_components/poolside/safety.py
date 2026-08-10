"""Fail-closed write authorization for Poolside Controls and Themes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .exceptions import RestrictedControlError, UnsafeWriteError
from .models import Control, Site, Theme

_BASE_CONTROL_FIELDS: Final = frozenset(
    {
        "AutoResumeStartTime",
        "OnUntil",
        "PowerLevel",
        "PowerLevelIdle",
        "PowerLevelRunning",
        "SetPoint",
        "Status",
        "WaterLevelingOnUntil",
    }
)
_LIGHT_FIELDS: Final = frozenset({"Brightness", "Color", "LightName", "Speed", "Twinkle"})
_PASSIVE_SETPOINT_FIELDS: Final = frozenset(
    {"PowerLevel", "PowerLevelIdle", "PowerLevelRunning", "SetPoint"}
)


class SafetyPolicy:
    """Authorize only confirmed high-level writes immediately before transport use."""

    def authorize_control(
        self, site: Site, target_uuid: str, changes: Mapping[str, Any]
    ) -> Control:
        """Authorize a discovered Control write and reject all physical equipment targets."""
        control = site.all_controls.get(target_uuid)
        if control is None:
            raise UnsafeWriteError("Write target is not a discovered Control")
        if control.restricted or control.installer_only:
            raise RestrictedControlError("Control is currently restricted or disabled")
        allowed = _BASE_CONTROL_FIELDS | (_LIGHT_FIELDS if control.is_light else frozenset())
        if not changes or not set(changes).issubset(allowed):
            raise UnsafeWriteError("Control write contains an unconfirmed field")
        if control.disabled_reasons and not set(changes).issubset(_PASSIVE_SETPOINT_FIELDS):
            raise RestrictedControlError("Control is currently restricted or disabled")
        return control

    def authorize_theme(self, site: Site, theme_uuid: str, status: str) -> Theme:
        """Authorize only the captured Theme activation operation."""
        theme = site.themes.get(theme_uuid)
        if theme is None:
            raise UnsafeWriteError("Write target is not a discovered Theme")
        if status != "ON":
            raise UnsafeWriteError("Theme deactivation has not been confirmed")
        return theme
