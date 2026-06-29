"""Adapter for Tado zone state — my.tado.com API. Python 3.9+ compatible."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict

from PyTado.const import (
    CONST_FAN_AUTO,
    CONST_FAN_OFF,
    CONST_FAN_SPEED_AUTO,
    CONST_FAN_SPEED_OFF,
    CONST_HORIZONTAL_SWING_OFF,
    CONST_HVAC_COOL,
    CONST_HVAC_HEAT,
    CONST_HVAC_IDLE,
    CONST_HVAC_OFF,
    CONST_LINK_OFFLINE,
    CONST_MODE_OFF,
    CONST_MODE_SMART_SCHEDULE,
    CONST_VERTICAL_SWING_OFF,
    DEFAULT_TADO_PRECISION,
    TADO_HVAC_ACTION_TO_MODES,
    TADO_MODES_TO_HVAC_ACTION,
    TYPE_AIR_CONDITIONING,
)

_LOGGER = logging.getLogger(__name__)


# kw_only=True removed for Python 3.9 compat (added in 3.10).
# Field ordering is preserved: zone_id (no default) first, all others optional.
@dataclasses.dataclass(frozen=True)
class TadoZone:
    """Tado Zone data structure for my.tado.com."""

    zone_id: int
    current_temp: float = None
    current_temp_timestamp: str = None
    current_humidity: float = None
    current_humidity_timestamp: str = None
    is_away: bool = None
    current_hvac_action: str = CONST_HVAC_OFF
    current_fan_speed: str = None
    current_fan_level: str = None
    current_hvac_mode: str = None
    current_swing_mode: str = None
    current_vertical_swing_mode: str = None
    current_horizontal_swing_mode: str = None
    target_temp: float = None
    available: bool = False
    power: str = None
    link: str = None
    connection: str = None
    ac_power_timestamp: str = None
    heating_power_timestamp: str = None
    ac_power: str = None
    heating_power: str = None
    heating_power_percentage: float = None
    tado_mode: str = None
    overlay_termination_type: str = None
    overlay_termination_timestamp: str = None
    default_overlay_termination_type: str = None
    default_overlay_termination_duration: str = None
    preparation: bool = False
    open_window: bool = False
    open_window_detected: bool = False
    open_window_attr: Dict[str, Any] = dataclasses.field(default_factory=dict)
    precision: float = DEFAULT_TADO_PRECISION

    @property
    def overlay_active(self) -> bool:
        return self.current_hvac_mode != CONST_MODE_SMART_SCHEDULE

    @classmethod
    def from_data(cls, zone_id: int, data: Dict[str, Any]) -> TadoZone:
        """Build a TadoZone from raw API state data."""
        _LOGGER.debug("Processing data from zone %d", zone_id)
        kwargs: Dict[str, Any] = {}

        if "sensorDataPoints" in data:
            sensor_data = data["sensorDataPoints"]
            if "insideTemperature" in sensor_data:
                kwargs["current_temp"] = float(sensor_data["insideTemperature"]["celsius"])
                kwargs["current_temp_timestamp"] = sensor_data["insideTemperature"]["timestamp"]
                if "precision" in sensor_data["insideTemperature"]:
                    kwargs["precision"] = sensor_data["insideTemperature"]["precision"]["celsius"]
            if "humidity" in sensor_data:
                kwargs["current_humidity"] = float(sensor_data["humidity"]["percentage"])
                kwargs["current_humidity_timestamp"] = sensor_data["humidity"]["timestamp"]

        if "tadoMode" in data:
            kwargs["is_away"] = data["tadoMode"] == "AWAY"
            kwargs["tado_mode"] = data["tadoMode"]

        if "link" in data:
            kwargs["link"] = data["link"]["state"]

        if "connection" in data:
            kwargs["connection"] = data["connection"]["state"]

        if "setting" in data:
            if "temperature" in data["setting"] and data["setting"]["temperature"] is not None:
                kwargs["target_temp"] = float(data["setting"]["temperature"]["celsius"])

            setting = data["setting"]
            kwargs.update({
                "current_fan_speed": None,
                "current_fan_level": None,
                "current_hvac_mode": CONST_MODE_OFF,
                "current_swing_mode": CONST_MODE_OFF,
                "current_vertical_swing_mode": CONST_VERTICAL_SWING_OFF,
                "current_horizontal_swing_mode": CONST_HORIZONTAL_SWING_OFF,
            })

            if "mode" in setting:
                kwargs["current_hvac_mode"] = setting["mode"]
            if "swing" in setting:
                kwargs["current_swing_mode"] = setting["swing"]
            if "verticalSwing" in setting:
                kwargs["current_vertical_swing_mode"] = setting["verticalSwing"]
            if "horizontalSwing" in setting:
                kwargs["current_horizontal_swing_mode"] = setting["horizontalSwing"]

            power = setting["power"]
            kwargs["power"] = power
            if power == "ON":
                kwargs["current_hvac_action"] = CONST_HVAC_IDLE
                if ("mode" not in setting and "type" in setting
                        and setting["type"] in TADO_HVAC_ACTION_TO_MODES):
                    kwargs["current_hvac_mode"] = TADO_HVAC_ACTION_TO_MODES[setting["type"]]

            if "fanSpeed" in setting:
                kwargs["current_fan_speed"] = setting.get(
                    "fanSpeed", CONST_FAN_AUTO if power == "ON" else CONST_FAN_OFF)
            elif "type" in setting and setting["type"] == TYPE_AIR_CONDITIONING:
                kwargs["current_fan_speed"] = CONST_FAN_AUTO if power == "ON" else CONST_FAN_OFF

            if "fanLevel" in setting:
                kwargs["current_fan_level"] = setting.get(
                    "fanLevel",
                    CONST_FAN_SPEED_AUTO if power == "ON" else CONST_FAN_SPEED_OFF)

        kwargs["preparation"] = "preparation" in data and data["preparation"] is not None
        kwargs["open_window"] = data.get("openWindow") is not None
        kwargs["open_window_detected"] = data.get("openWindowDetected", False)
        kwargs["open_window_attr"] = data.get("openWindow") or {}

        if "activityDataPoints" in data:
            activity_data = data["activityDataPoints"]
            if "acPower" in activity_data and activity_data["acPower"] is not None:
                kwargs["ac_power"] = activity_data["acPower"]["value"]
                kwargs["ac_power_timestamp"] = activity_data["acPower"]["timestamp"]
                if activity_data["acPower"]["value"] == "ON" and power == "ON":
                    kwargs["current_hvac_action"] = TADO_MODES_TO_HVAC_ACTION.get(
                        kwargs["current_hvac_mode"], CONST_HVAC_COOL)
            if "heatingPower" in activity_data and activity_data["heatingPower"] is not None:
                kwargs["heating_power"] = activity_data["heatingPower"].get("value")
                kwargs["heating_power_timestamp"] = activity_data["heatingPower"]["timestamp"]
                kwargs["heating_power_percentage"] = float(
                    activity_data["heatingPower"].get("percentage", 0))
                if kwargs["heating_power_percentage"] > 0.0 and power == "ON":
                    kwargs["current_hvac_action"] = CONST_HVAC_HEAT

        if "overlay" in data and data["overlay"] is not None:
            if "termination" in data["overlay"] and "type" in data["overlay"]["termination"]:
                kwargs["overlay_termination_type"] = data["overlay"]["termination"]["type"]
                kwargs["overlay_termination_timestamp"] = data["overlay"]["termination"].get(
                    "expiry")
        else:
            kwargs["current_hvac_mode"] = CONST_MODE_SMART_SCHEDULE

        kwargs["connection"] = (
            data["connectionState"]["value"] if "connectionState" in data else None)
        kwargs["available"] = kwargs.get("link") != CONST_LINK_OFFLINE

        if "terminationCondition" in data:
            kwargs["default_overlay_termination_type"] = data["terminationCondition"].get("type")
            kwargs["default_overlay_termination_duration"] = data["terminationCondition"].get(
                "durationInSeconds")

        return cls(zone_id=zone_id, **kwargs)
