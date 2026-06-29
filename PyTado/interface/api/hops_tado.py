"""PyTado interface — hops.tado.com (Tado X) API. Python 3.9+ compatible."""

from __future__ import annotations

import functools
import logging
from typing import Any, Dict, List

from ...exceptions import TadoNotSupportedException
from ...http import Action, Domain, Http, Mode, TadoRequest, TadoXRequest
from ...logger import Logger
from ...zone import TadoXZone, TadoZone
from .my_tado import Tado, Timetable


def not_supported(reason: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            raise TadoNotSupportedException(f"{func.__name__} is not supported: {reason}")
        return wrapper
    return decorator


_LOGGER = Logger(__name__)


class TadoX(Tado):
    """Interacts with a Tado thermostat via hops.tado.com (Tado X) API."""

    def __init__(self, http: Http, debug: bool = False):
        super().__init__(http=http, debug=debug)
        if not http.is_x_line:
            raise TadoNotSupportedException("TadoX is only usable with LINE_X Generation")
        if debug:
            _LOGGER.setLevel(logging.DEBUG)
        else:
            _LOGGER.setLevel(logging.WARNING)
        self._http = http
        self._auto_geofencing_supported = None

    def get_devices(self) -> List[Dict[str, Any]]:
        rooms_and_devices: Dict[str, Any] = self._http.request(
            TadoXRequest(command="roomsAndDevices")
        )
        rooms = rooms_and_devices["rooms"]
        devices = [device for room in rooms for device in room["devices"]]

        for device in devices:
            serial_number = device.get("serialNo", device.get("serialNumber"))
            if not serial_number:
                continue
            device.update(self._http.request(
                TadoXRequest(domain=Domain.DEVICES, device=serial_number)
            ))

        if "otherDevices" in rooms_and_devices:
            devices.append(rooms_and_devices["otherDevices"])

        return devices

    def get_zones(self):
        return self._http.request(TadoXRequest(command="roomsAndDevices"))["rooms"]

    def get_zone_state(self, zone: int) -> TadoZone:
        return TadoXZone.from_data(zone, self.get_state(zone))

    def get_zone_states(self):
        return self._http.request(TadoXRequest(command="rooms"))

    def get_state(self, zone: int):
        return self._http.request(TadoXRequest(command=f"rooms/{zone:d}"))

    @not_supported("This method is not currently supported by the Tado X API")
    def get_capabilities(self, zone):
        pass

    def get_climate(self, zone):
        data = self.get_state(zone)["sensorDataPoints"]
        return {
            "temperature": data["insideTemperature"]["value"],
            "humidity": data["humidity"]["percentage"],
        }

    @not_supported("Tado X API only supports seven-day timetable")
    def set_timetable(self, zone: int, timetable: Timetable) -> None:
        pass

    def get_schedule(self, zone: int, timetable: Timetable, day=None) -> Dict[str, Any]:
        return self._http.request(TadoXRequest(command=f"rooms/{zone:d}/schedule"))

    def set_schedule(self, zone: int, timetable: Timetable, day, data):
        return self._http.request(TadoXRequest(
            command=f"rooms/{zone:d}/schedule",
            action=Action.SET,
            payload=data,
            mode=Mode.OBJECT,
        ))

    def reset_zone_overlay(self, zone: int):
        return self._http.request(TadoXRequest(
            command=f"rooms/{zone:d}/resumeSchedule",
            action=Action.SET,
        ))

    def set_zone_overlay(
        self, zone, overlay_mode, set_temp=None, duration=None,
        device_type="HEATING", power="ON", mode=None, fan_speed=None,
        swing=None, fan_level=None, vertical_swing=None, horizontal_swing=None,
    ):
        post_data: Dict[str, Any] = {
            "setting": {"type": device_type, "power": power},
            "termination": {"type": overlay_mode},
        }
        if set_temp is not None:
            post_data["setting"]["temperature"] = {
                "value": set_temp,
                "valueRaw": set_temp,
                "precision": 0.1,
            }
        if duration is not None:
            post_data["termination"]["durationInSeconds"] = duration

        return self._http.request(TadoXRequest(
            command=f"rooms/{zone:d}/manualControl",
            action=Action.SET,
            payload=post_data,
        ))

    @not_supported("Tado X uses rooms, not zones — overlay defaults are not exposed by the API")
    def get_zone_overlay_default(self, zone: int):
        pass

    def get_open_window_detected(self, zone: int):
        data = self.get_state(zone)
        detected = bool(data.get("openWindow") and "activated" in data["openWindow"])
        return {"openWindowDetected": detected}

    def set_open_window(self, zone: int):
        return self._http.request(TadoXRequest(
            command=f"rooms/{zone}/openWindow",
            action=Action.SET,
        ))

    def reset_open_window(self, zone: int):
        return self._http.request(TadoXRequest(
            command=f"rooms/{zone}/openWindow",
            action=Action.RESET,
        ))

    def get_device_info(self, device_id, cmd=""):
        if cmd:
            request = TadoRequest(
                command=cmd,
                action=Action.GET,
                domain=Domain.DEVICES,
                device=device_id,
            )
        else:
            request = TadoXRequest(
                action=Action.GET,
                domain=Domain.DEVICES,
                device=device_id,
            )
        return self._http.request(request)

    def set_temp_offset(self, device_id, offset=0, measure="celsius"):
        return self._http.request(TadoXRequest(
            command=f"roomsAndDevices/devices/{device_id}",
            action=Action.CHANGE,
            payload={"temperatureOffset": offset},
        ))

    def set_child_lock(self, device_id, child_lock) -> None:
        self._http.request(TadoXRequest(
            command=f"roomsAndDevices/devices/{device_id}",
            action=Action.CHANGE,
            payload={"childLockEnabled": child_lock},
        ))

    def set_flow_temperature_optimization(self, max_flow_temperature: float):
        return self._http.request(TadoXRequest(
            action=Action.CHANGE,
            domain=Domain.HOME,
            command="settings/flowTemperatureOptimization",
            payload={"maxFlowTemperature": max_flow_temperature},
        ))

    def get_flow_temperature_optimization(self):
        return self._http.request(TadoXRequest(
            action=Action.GET,
            domain=Domain.HOME,
            command="settings/flowTemperatureOptimization",
        ))
