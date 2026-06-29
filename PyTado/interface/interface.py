"""
PyTado interface — fixed fork of python-tado 0.19.2

Main change vs upstream: client_id is a constructor parameter instead of a
module-level global. Pass Tado(client_id="...") instead of patching
PyTado.const.CLIENT_ID_DEVICE before instantiating.
"""

from __future__ import annotations

import datetime
import functools
import warnings
from typing import Optional

import requests

import PyTado.interface.api as API
from PyTado.exceptions import TadoException
from PyTado.http import DeviceActivationStatus, Http


def deprecated(new_func_name: str):
    """Mark a method as deprecated, pointing to its replacement."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"'{func.__name__}' is deprecated — use '{new_func_name}' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return getattr(args[0], new_func_name)(*args[1:], **kwargs)
        return wrapper
    return decorator


class Tado:
    """
    Entry point for the Tado API.

    Usage:
        tado = Tado(token_file_path="/path/to/token")
        if tado.device_activation_status() == DeviceActivationStatus.PENDING:
            print("Visit:", tado.device_verification_url())
            tado.device_activation()   # blocks until approved
        zones = tado.get_zones()
    """

    def __init__(
        self,
        token_file_path: Optional[str] = None,
        saved_refresh_token: Optional[str] = None,
        http_session: Optional[requests.Session] = None,
        debug: bool = False,
        client_id: Optional[str] = None,
    ):
        """
        Args:
            token_file_path: Path to persist the refresh token across restarts.
            saved_refresh_token: A previously obtained refresh token.
            http_session: Optional pre-configured requests.Session.
            debug: Enable HTTP-level debug logging.
            client_id: OAuth2 client_id. Defaults to CLIENT_ID_DEVICE from const.py.
                       Replaces the need to monkey-patch PyTado.const.CLIENT_ID_DEVICE.
        """
        self._http = Http(
            token_file_path=token_file_path,
            saved_refresh_token=saved_refresh_token,
            http_session=http_session,
            debug=debug,
            client_id=client_id,
        )
        self._api: Optional[API.Tado | API.TadoX] = None
        self._debug = debug

    def __getattr__(self, name: str):
        """Delegate unknown methods to the appropriate API implementation."""
        self._ensure_api_initialized()
        return getattr(self._api, name)

    # ── Device flow ───────────────────────────────────────────────────────────

    def device_verification_url(self) -> Optional[str]:
        """Return the URL the user must visit to authorize the device."""
        return self._http.device_verification_url

    def device_activation_status(self) -> DeviceActivationStatus:
        """Return the current device activation status."""
        return self._http.device_activation_status

    def device_activation(self) -> None:
        """Block until the user has approved the device flow, then initialize the API."""
        self._http.device_activation()
        self._ensure_api_initialized()

    def get_refresh_token(self) -> Optional[str]:
        """Return the current refresh token (useful for external persistence)."""
        return self._http.refresh_token

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_api_initialized(self) -> None:
        if self._api is not None:
            return
        if self._http.device_activation_status != DeviceActivationStatus.COMPLETED:
            raise TadoException(
                "API not ready. Complete device authorization first "
                f"(status: {self._http.device_activation_status})."
            )
        if self._http.is_x_line:
            self._api = API.TadoX(http=self._http, debug=self._debug)
        else:
            self._api = API.Tado(http=self._http, debug=self._debug)

    # ── Deprecated aliases ────────────────────────────────────────────────────

    @deprecated("get_me")
    def getMe(self):
        return self.get_me()

    @deprecated("get_devices")
    def getDevices(self):
        return self.get_devices()

    @deprecated("get_zones")
    def getZones(self):
        return self.get_zones()

    @deprecated("get_zone_state")
    def getZoneState(self, zone):
        return self.get_zone_state(zone)

    @deprecated("get_zone_states")
    def getZoneStates(self):
        return self.get_zone_states()

    @deprecated("get_state")
    def getState(self, zone):
        return self.get_state(zone)

    @deprecated("get_home_state")
    def getHomeState(self):
        return self.get_home_state()

    @deprecated("get_capabilities")
    def getCapabilities(self, zone):
        return self.get_capabilities(zone)

    @deprecated("get_climate")
    def getClimate(self, zone):
        return self.get_climate(zone)

    @deprecated("get_timetable")
    def getTimetable(self, zone):
        return self.get_timetable(zone)

    @deprecated("get_historic")
    def getHistoric(self, zone, date):
        return self.get_historic(zone, date)

    @deprecated("set_timetable")
    def setTimetable(self, zone, _id):
        return self.set_timetable(zone, _id)

    @deprecated("get_schedule")
    def getSchedule(self, zone, _id, day=None):
        return self.get_schedule(zone, _id, day)

    @deprecated("set_schedule")
    def setSchedule(self, zone, _id, day, data):
        return self.set_schedule(zone, _id, day, data)

    @deprecated("get_weather")
    def getWeather(self):
        return self.get_weather()

    @deprecated("get_air_comfort")
    def getAirComfort(self):
        return self.get_air_comfort()

    @deprecated("get_mobile_devices")
    def getMobileDevices(self):
        return self.get_mobile_devices()

    @deprecated("reset_zone_overlay")
    def resetZoneOverlay(self, zone):
        return self.reset_zone_overlay(zone)

    @deprecated("set_zone_overlay")
    def setZoneOverlay(self, zone, overlayMode, setTemp=None, duration=None,
                       deviceType="HEATING", power="ON", mode=None, fanSpeed=None,
                       swing=None, fanLevel=None, verticalSwing=None, horizontalSwing=None):
        return self.set_zone_overlay(
            zone, overlay_mode=overlayMode, set_temp=setTemp, duration=duration,
            device_type=deviceType, power=power, mode=mode, fan_speed=fanSpeed,
            swing=swing, fan_level=fanLevel, vertical_swing=verticalSwing,
            horizontal_swing=horizontalSwing,
        )

    @deprecated("get_zone_overlay_default")
    def getZoneOverlayDefault(self, zone):
        return self.get_zone_overlay_default(zone)

    @deprecated("set_home")
    def setHome(self):
        return self.set_home()

    @deprecated("set_away")
    def setAway(self):
        return self.set_away()

    @deprecated("change_presence")
    def changePresence(self, presence):
        return self.change_presence(presence=presence)

    @deprecated("set_auto")
    def setAuto(self):
        return self.set_auto()

    @deprecated("get_eiq_tariffs")
    def getEIQTariffs(self):
        return self.get_eiq_tariffs()

    @deprecated("get_eiq_meter_readings")
    def getEIQMeterReadings(self):
        return self.get_eiq_meter_readings()

    @deprecated("set_eiq_meter_readings")
    def setEIQMeterReadings(
        self,
        date=datetime.datetime.now().strftime("%Y-%m-%d"),
        reading=0,
    ):
        return self.set_eiq_meter_readings(date=date, reading=reading)

    @deprecated("set_eiq_tariff")
    def setEIQTariff(
        self,
        from_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        to_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        tariff=0,
        unit="m3",
        is_period=False,
    ):
        return self.set_eiq_tariff(
            from_date=from_date, to_date=to_date,
            tariff=tariff, unit=unit, is_period=is_period,
        )
