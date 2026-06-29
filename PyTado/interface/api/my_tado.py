"""PyTado interface — my.tado.com API. Python 3.9+ compatible."""

from __future__ import annotations

import datetime
import enum
import logging
from typing import Any, Dict

from ...exceptions import TadoException, TadoNotSupportedException
from ...http import Action, Domain, Endpoint, Http, Mode, TadoRequest
from ...logger import Logger
from ...zone import TadoZone


class Timetable(enum.IntEnum):
    ONE_DAY   = 0
    THREE_DAY = 1
    SEVEN_DAY = 2


class Presence(str, enum.Enum):
    HOME = "HOME"
    AWAY = "AWAY"


_LOGGER = Logger(__name__)


class Tado:
    """Interacts with a Tado thermostat via my.tado.com API."""

    def __init__(self, http: Http, debug: bool = False):
        if debug:
            _LOGGER.setLevel(logging.DEBUG)
        else:
            _LOGGER.setLevel(logging.WARNING)
        self._http = http
        self._auto_geofencing_supported = None

    def get_me(self):
        request = TadoRequest(action=Action.GET, domain=Domain.ME)
        return self._http.request(request)

    def get_devices(self):
        request = TadoRequest(command="devices")
        return self._http.request(request)

    def get_zones(self):
        request = TadoRequest(command="zones")
        return self._http.request(request)

    def get_zone_state(self, zone: int) -> TadoZone:
        return TadoZone.from_data(zone, self.get_state(zone))

    def get_zone_states(self):
        request = TadoRequest(command="zoneStates")
        return self._http.request(request)

    def get_state(self, zone):
        request = TadoRequest(command=f"zones/{zone}/state")
        return {**self._http.request(request), **self.get_zone_overlay_default(zone)}

    def get_home_state(self):
        request = TadoRequest(command="state")
        data = self._http.request(request)
        if "showSwitchToAutoGeofencingButton" in data:
            self._auto_geofencing_supported = data["showSwitchToAutoGeofencingButton"]
        elif "presenceLocked" in data:
            self._auto_geofencing_supported = not data["presenceLocked"]
        else:
            self._auto_geofencing_supported = False
        return data

    def get_auto_geofencing_supported(self):
        if self._auto_geofencing_supported is None:
            self.get_home_state()
        return self._auto_geofencing_supported

    def get_capabilities(self, zone):
        request = TadoRequest(command=f"zones/{zone:d}/capabilities")
        return self._http.request(request)

    def get_climate(self, zone):
        data = self.get_state(zone)["sensorDataPoints"]
        return {
            "temperature": data["insideTemperature"]["celsius"],
            "humidity": data["humidity"]["percentage"],
        }

    def get_timetable(self, zone: int) -> Timetable:
        request = TadoRequest(command=f"zones/{zone:d}/schedule/activeTimetable", mode=Mode.PLAIN)
        data = self._http.request(request)
        if "id" not in data:
            raise TadoException(f'Response missing "id": {data}')
        return Timetable(data["id"])

    def get_historic(self, zone, date):
        try:
            day = datetime.datetime.strptime(date, "%Y-%m-%d")
        except ValueError as err:
            raise ValueError("Date format must be YYYY-MM-DD") from err
        request = TadoRequest(command=f"zones/{zone:d}/dayReport?date={day.strftime('%Y-%m-%d')}")
        return self._http.request(request)

    def set_timetable(self, zone: int, timetable: Timetable) -> None:
        request = TadoRequest(
            command=f"zones/{zone:d}/schedule/activeTimetable",
            action=Action.CHANGE,
            payload={"id": timetable},
            mode=Mode.PLAIN,
        )
        self._http.request(request)

    def get_schedule(self, zone: int, timetable: Timetable, day=None) -> Dict[str, Any]:
        cmd = (
            f"zones/{zone:d}/schedule/timetables/{timetable:d}/blocks/{day}"
            if day else
            f"zones/{zone:d}/schedule/timetables/{timetable:d}/blocks"
        )
        request = TadoRequest(command=cmd, mode=Mode.PLAIN)
        return self._http.request(request)

    def set_schedule(self, zone, timetable: Timetable, day, data):
        request = TadoRequest(
            command=f"zones/{zone:d}/schedule/timetables/{timetable:d}/blocks/{day}",
            action=Action.CHANGE,
            payload=data,
            mode=Mode.PLAIN,
        )
        return self._http.request(request)

    def get_weather(self):
        return self._http.request(TadoRequest(command="weather"))

    def get_air_comfort(self):
        return self._http.request(TadoRequest(command="airComfort"))

    def get_users(self):
        return self._http.request(TadoRequest(command="users"))

    def get_mobile_devices(self):
        return self._http.request(TadoRequest(command="mobileDevices"))

    def reset_zone_overlay(self, zone):
        request = TadoRequest(
            command=f"zones/{zone:d}/overlay",
            action=Action.RESET,
            mode=Mode.PLAIN,
        )
        return self._http.request(request)

    def set_zone_overlay(
        self, zone, overlay_mode, set_temp=None, duration=None,
        device_type="HEATING", power="ON", mode=None, fan_speed=None,
        swing=None, fan_level=None, vertical_swing=None, horizontal_swing=None,
    ):
        post_data = {
            "setting": {"type": device_type, "power": power},
            "termination": {"typeSkillBasedApp": overlay_mode},
        }
        if set_temp is not None:
            post_data["setting"]["temperature"] = {"celsius": set_temp}
            if fan_speed is not None:
                post_data["setting"]["fanSpeed"] = fan_speed
            elif fan_level is not None:
                post_data["setting"]["fanLevel"] = fan_level
            if swing is not None:
                post_data["setting"]["swing"] = swing
            else:
                if vertical_swing is not None:
                    post_data["setting"]["verticalSwing"] = vertical_swing
                if horizontal_swing is not None:
                    post_data["setting"]["horizontalSwing"] = horizontal_swing
        if mode is not None:
            post_data["setting"]["mode"] = mode
        if duration is not None:
            post_data["termination"]["durationInSeconds"] = duration

        request = TadoRequest(
            command=f"zones/{zone:d}/overlay",
            action=Action.CHANGE,
            payload=post_data,
        )
        return self._http.request(request)

    def get_zone_overlay_default(self, zone: int):
        request = TadoRequest(command=f"zones/{zone:d}/defaultOverlay")
        return self._http.request(request)

    def set_home(self) -> None:
        return self.change_presence(Presence.HOME)

    def set_away(self) -> None:
        return self.change_presence(Presence.AWAY)

    def change_presence(self, presence: Presence) -> None:
        request = TadoRequest(
            command="presenceLock",
            action=Action.CHANGE,
            payload={"homePresence": presence},
        )
        self._http.request(request)

    def set_child_lock(self, device_id, child_lock) -> None:
        request = TadoRequest(
            command="childLock",
            action=Action.CHANGE,
            domain=Domain.DEVICES,
            device=device_id,
            payload={"childLockEnabled": child_lock},
        )
        self._http.request(request)

    def set_auto(self) -> None:
        if self._auto_geofencing_supported:
            request = TadoRequest(command="presenceLock", action=Action.RESET)
            return self._http.request(request)
        raise TadoNotSupportedException("Auto geofencing is not supported on this home.")

    def get_window_state(self, zone):
        return {"openWindow": self.get_state(zone)["openWindow"]}

    def get_open_window_detected(self, zone):
        data = self.get_state(zone)
        return {"openWindowDetected": data.get("openWindowDetected", False)}

    def set_open_window(self, zone):
        request = TadoRequest(
            command=f"zones/{zone:d}/state/openWindow/activate",
            action=Action.SET,
            mode=Mode.PLAIN,
        )
        return self._http.request(request)

    def reset_open_window(self, zone):
        request = TadoRequest(
            command=f"zones/{zone:d}/state/openWindow",
            action=Action.RESET,
            mode=Mode.PLAIN,
        )
        return self._http.request(request)

    def get_device_info(self, device_id, cmd=""):
        request = TadoRequest(
            command=cmd,
            action=Action.GET,
            domain=Domain.DEVICES,
            device=device_id,
        )
        return self._http.request(request)

    def set_temp_offset(self, device_id, offset=0, measure="celsius"):
        request = TadoRequest(
            command="temperatureOffset",
            action=Action.CHANGE,
            domain=Domain.DEVICES,
            device=device_id,
            payload={measure: offset},
        )
        return self._http.request(request)

    def get_eiq_tariffs(self):
        request = TadoRequest(command="tariffs", action=Action.GET, endpoint=Endpoint.EIQ)
        return self._http.request(request)

    def get_eiq_meter_readings(self):
        request = TadoRequest(command="meterReadings", action=Action.GET, endpoint=Endpoint.EIQ)
        return self._http.request(request)

    def set_eiq_meter_readings(
        self, date=datetime.datetime.now().strftime("%Y-%m-%d"), reading=0
    ):
        request = TadoRequest(
            command="meterReadings",
            action=Action.SET,
            endpoint=Endpoint.EIQ,
            payload={"date": date, "reading": reading},
        )
        return self._http.request(request)

    def set_eiq_tariff(
        self,
        from_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        to_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        tariff=0,
        unit="m3",
        is_period=False,
    ):
        tariff_in_cents = tariff * 100
        payload = {
            "tariffInCents": tariff_in_cents,
            "unit": unit,
            "startDate": from_date,
        }
        if is_period:
            payload["endDate"] = to_date
        request = TadoRequest(
            command="tariffs", action=Action.SET, endpoint=Endpoint.EIQ, payload=payload)
        return self._http.request(request)

    def get_heating_circuits(self):
        return self._http.request(TadoRequest(command="heatingCircuits"))

    def get_zone_control(self, zone):
        return self._http.request(TadoRequest(command=f"zones/{zone:d}/control"))

    def set_zone_heating_circuit(self, zone, heating_circuit):
        request = TadoRequest(
            command=f"zones/{zone:d}/control/heatingCircuit",
            action=Action.CHANGE,
            payload={"circuitNumber": heating_circuit},
        )
        return self._http.request(request)

    def get_running_times(self, date=datetime.datetime.now().strftime("%Y-%m-%d")) -> dict:
        request = TadoRequest(
            command="runningTimes",
            action=Action.GET,
            endpoint=Endpoint.MINDER,
            params={"from": date},
        )
        return self._http.request(request)
