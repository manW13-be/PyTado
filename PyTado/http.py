"""
PyTado HTTP layer — fixed fork of python-tado 0.19.2

Fixes vs upstream:
  1. device_verification_url now includes client_id (upstream omits it → auth server rejects)
  2. _refresh_token uses form-encoded body (upstream sends params as query string + empty JSON body)
  3. _check_device_activation uses same form-encoded format for consistency
  4. Expired/invalid token with existing token file now falls back to device flow automatically
     instead of leaving the client stuck in NOT_STARTED with no recovery path
  5. client_id accepted as constructor parameter — no more module-level global mutation
     (CLIENT_ID_DEVICE in const.py is kept as the default value only)
"""

from __future__ import annotations

import enum
import json
import logging
import os
import pprint
import time
from datetime import datetime, timedelta, timezone
from json import dump as json_dump
from json import load as json_load
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests

import PyTado.const as _const
from PyTado.exceptions import TadoException, TadoWrongCredentialsException
from PyTado.logger import Logger

_LOGGER = Logger(__name__)

_AUTH_URL     = "https://login.tado.com/oauth2/token"
_DEVICE_URL   = "https://login.tado.com/oauth2/device_authorize"
_REFERER      = "https://app.tado.com/"
_DEFAULT_TIMEOUT = 10
_DEFAULT_RETRIES = 5


class Endpoint(str, enum.Enum):
    """Endpoint URL Enum"""
    MY_API   = "https://my.tado.com/api/v2/"
    HOPS_API = "https://hops.tado.com/"
    MOBILE   = "https://my.tado.com/mobile/1.9/"
    EIQ      = "https://energy-insights.tado.com/api/"
    TARIFF   = "https://tariff-experience.tado.com/api/"
    GENIE    = "https://genie.tado.com/api/v2/"
    MINDER   = "https://minder.tado.com/v1/"


class Domain(str, enum.Enum):
    """API Request Domain Enum"""
    HOME           = "homes"
    DEVICES        = "devices"
    ME             = "me"
    HOME_BY_BRIDGE = "homeByBridge"


class Action(str, enum.Enum):
    """API Request Action Enum"""
    GET    = "GET"
    SET    = "POST"
    RESET  = "DELETE"
    CHANGE = "PUT"


class Mode(enum.Enum):
    """API Response Format Enum"""
    OBJECT = 1
    PLAIN  = 2


class DeviceActivationStatus(str, enum.Enum):
    """Device Activation Status Enum"""
    NOT_STARTED = "NOT_STARTED"
    PENDING     = "PENDING"
    COMPLETED   = "COMPLETED"


class TadoRequest:
    """Data Container for my.tado.com API Requests"""

    def __init__(
        self,
        endpoint: Endpoint = Endpoint.MY_API,
        command: Optional[str] = None,
        action: Action = Action.GET,
        payload: Optional[dict] = None,
        domain: Domain = Domain.HOME,
        device: Optional[Any] = None,
        mode: Mode = Mode.OBJECT,
        params: Optional[dict] = None,
    ) -> None:
        self.endpoint = endpoint
        self.command  = command
        self.action   = action
        self.payload  = payload
        self.domain   = domain
        self.device   = device
        self.mode     = mode
        self.params   = params


class TadoXRequest(TadoRequest):
    """Data Container for hops.tado.com (Tado X) API Requests"""

    def __init__(
        self,
        endpoint: Endpoint = Endpoint.HOPS_API,
        command: Optional[str] = None,
        action: Action = Action.GET,
        payload: Optional[dict] = None,
        domain: Domain = Domain.HOME,
        device: Optional[Any] = None,
        mode: Mode = Mode.OBJECT,
        params: Optional[dict] = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint, command=command, action=action,
            payload=payload, domain=domain, device=device, mode=mode, params=params,
        )
        self._action = action

    @property
    def action(self) -> Action:
        if self._action == Action.CHANGE:
            return "PATCH"
        return self._action

    @action.setter
    def action(self, value: Action) -> None:
        self._action = value


class Http:
    """API Request Class — fixed fork of python-tado 0.19.2"""

    def __init__(
        self,
        token_file_path: Optional[str] = None,
        saved_refresh_token: Optional[str] = None,
        http_session: Optional[requests.Session] = None,
        debug: bool = False,
        client_id: Optional[str] = None,      # FIX 5: per-instance client_id
    ) -> None:
        """
        Args:
            token_file_path: Path where the refresh token is persisted.
            saved_refresh_token: Pre-existing refresh token (alternative to file).
            http_session: Optional pre-configured requests.Session.
            debug: Enable debug logging.
            client_id: OAuth2 client_id. Defaults to CLIENT_ID_DEVICE from const.py.
                       Pass explicitly instead of monkey-patching PyTado.const.CLIENT_ID_DEVICE.
        """
        if debug:
            _LOGGER.setLevel(logging.DEBUG)
        else:
            _LOGGER.setLevel(logging.WARNING)

        # FIX 5: store client_id per-instance; fall back to module-level default
        self._client_id = client_id or _const.CLIENT_ID_DEVICE

        self._refresh_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        self._session    = http_session or self._create_session()
        self._headers    = {"Referer": _REFERER}

        self._user_code:               Optional[str]      = None
        self._device_verification_url: Optional[str]      = None
        self._device_activation_status = DeviceActivationStatus.NOT_STARTED
        self._expires_at:              Optional[datetime] = None
        self._device_flow_data:        Optional[dict]     = None

        self._id:            Optional[int]  = None
        self._token_refresh: Optional[str]  = None
        self._x_api:         Optional[bool] = None
        self._token_file_path = token_file_path

        if saved_refresh_token or self._load_token():
            if self._refresh_token(refresh_token=saved_refresh_token, force_refresh=True):
                self._device_ready()
            else:
                # FIX 4: token file exists but token is expired/invalid → start device flow
                # Upstream leaves the client stuck in NOT_STARTED with no recovery path.
                _LOGGER.warning(
                    "Stored token is invalid or expired. Starting device flow."
                )
                self._device_activation_status = self._login_device_flow()
        else:
            self._device_activation_status = self._login_device_flow()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_x_line(self) -> Optional[bool]:
        return self._x_api

    @property
    def user_code(self) -> Optional[str]:
        return self._user_code

    @property
    def device_activation_status(self) -> DeviceActivationStatus:
        return self._device_activation_status

    @property
    def device_verification_url(self) -> Optional[str]:
        return self._device_verification_url

    @property
    def refresh_token(self) -> Optional[str]:
        return self._token_refresh

    # ── Session ───────────────────────────────────────────────────────────────

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.hooks["response"].append(self._log_response)
        return session

    def _log_response(self, response: requests.Response, *args, **kwargs) -> None:
        _LOGGER.debug(
            "\nRequest:\n\tMethod: %s\n\tURL: %s\nResponse:\n\tStatus: %s\n\tData: %s",
            response.request.method,
            response.request.url,
            response.status_code,
            pprint.pformat(response.json() if response.text else {}),
        )

    # ── API Request ───────────────────────────────────────────────────────────

    def request(self, request: TadoRequest) -> dict:
        """Execute an API request. Refreshes the access token automatically."""
        self._refresh_token()

        headers = dict(self._headers)
        body    = self._configure_payload(headers, request)
        url     = self._configure_url(request)

        http_req = requests.Request(method=request.action, url=url, headers=headers, data=body)
        prepped  = http_req.prepare()

        retries = _DEFAULT_RETRIES
        while retries >= 0:
            try:
                response = self._session.send(prepped, timeout=_DEFAULT_TIMEOUT)
                break
            except TadoWrongCredentialsException as exc:
                raise exc
            except requests.exceptions.ConnectionError as exc:
                if retries > 0:
                    _LOGGER.warning("Connection error: %s — retrying", exc)
                    self._session.close()
                    self._session = self._create_session()
                    retries -= 1
                else:
                    raise TadoException(exc) from exc

        if not response.text:
            return {}
        return response.json()

    def _configure_url(self, request: TadoRequest) -> str:
        if request.endpoint == Endpoint.MOBILE:
            url = f"{request.endpoint}{request.command}"
        elif request.domain in (Domain.DEVICES, Domain.HOME_BY_BRIDGE):
            url = f"{request.endpoint}{request.domain}/{request.device}/{request.command}"
        elif request.domain == Domain.ME:
            url = f"{request.endpoint}{request.domain}"
        else:
            url = f"{request.endpoint}{request.domain}/{self._id:d}/{request.command}"

        if request.params is not None:
            url += f"?{urlencode(request.params)}"
        return url

    def _configure_payload(self, headers: dict, request: TadoRequest) -> bytes:
        if request.payload is None:
            return b""
        if request.mode == Mode.PLAIN:
            headers["Content-Type"] = "text/plain;charset=UTF-8"
        else:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        headers["Mime-Type"] = "application/json;charset=UTF-8"
        return json.dumps(request.payload).encode("utf-8")

    # ── OAuth2 token management ───────────────────────────────────────────────

    def _set_oauth_header(self, data: dict) -> None:
        access_token  = data["access_token"]
        expires_in    = float(data["expires_in"])
        refresh_token = data["refresh_token"]

        self._token_refresh = refresh_token
        self._refresh_at    = (
            datetime.now(timezone.utc)
            + timedelta(seconds=expires_in)
            - timedelta(seconds=30)
        )
        self._headers["Authorization"] = f"Bearer {access_token}"
        self._save_token()

    def _load_token(self) -> bool:
        """Load refresh token from file. Returns True if a token was found."""
        if not self._token_file_path or not os.path.exists(self._token_file_path):
            return False
        try:
            with open(self._token_file_path, encoding="utf-8") as f:
                self._token_refresh = json_load(f).get("refresh_token")
            return bool(self._token_refresh)
        except (OSError, json.JSONDecodeError) as exc:
            _LOGGER.error("Failed to load token: %s", exc)
            raise TadoException(exc) from exc

    def _refresh_token(
        self,
        refresh_token: Optional[str] = None,
        force_refresh: bool = False,
    ) -> bool:
        """
        Refresh the OAuth access token.

        FIX 2/3: uses form-encoded body (application/x-www-form-urlencoded) instead of
        upstream's query-string + empty JSON body. The Tado login server requires the
        parameters to be in the request body, not the URL.
        """
        if self._refresh_at >= datetime.now(timezone.utc) and not force_refresh:
            return True

        data = {
            "client_id":     self._client_id,
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token or self._token_refresh,
        }

        self._session.close()
        self._session = self._create_session()

        try:
            response = self._session.request(
                "POST",
                _AUTH_URL,
                data=urlencode(data),           # form-encoded body
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer":      _REFERER,
                },
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.exceptions.ConnectionError as exc:
            raise TadoException(exc) from exc

        if response.status_code != 200:
            if force_refresh:
                _LOGGER.error(
                    "Token refresh failed (status %s). Token is expired or invalid.",
                    response.status_code,
                )
                return False
            raise TadoWrongCredentialsException(
                f"Token refresh failed. Status: {response.status_code}"
            )

        self._set_oauth_header(response.json())
        return True

    def _save_token(self) -> None:
        """Save the current refresh token to file."""
        if not self._token_file_path or not self._token_refresh:
            return
        try:
            token_dir = os.path.dirname(self._token_file_path)
            if token_dir:
                Path(token_dir).mkdir(parents=True, exist_ok=True)
            with open(self._token_file_path, "w", encoding="utf-8") as f:
                json_dump({"refresh_token": self._token_refresh}, f)
        except Exception as exc:
            _LOGGER.error("Failed to save token: %s", exc)
            raise TadoException(exc) from exc

    # ── OAuth2 device flow ────────────────────────────────────────────────────

    def _login_device_flow(self) -> DeviceActivationStatus:
        """
        Start the OAuth2 device authorization flow.

        FIX 1 (partial): the verification URL is built with both user_code AND client_id,
        so the Tado auth server can identify the application. Upstream only adds user_code.
        FIX 3: sends params as form-encoded body, consistent with _refresh_token.
        """
        if self._device_activation_status != DeviceActivationStatus.NOT_STARTED:
            raise TadoException("Device flow already started")

        data = {
            "client_id": self._client_id,
            "scope":     "offline_access",
        }

        try:
            response = self._session.request(
                "POST",
                _DEVICE_URL,
                data=urlencode(data),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer":      _REFERER,
                },
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.exceptions.ConnectionError as exc:
            raise TadoException(exc) from exc

        if response.status_code != 200:
            raise TadoException(
                f"Device flow init failed. Status {response.status_code}: {response.reason}"
            )

        self._device_flow_data = response.json()

        # FIX 1: include client_id in verification URL so the auth server can identify the app.
        # Upstream builds: verification_uri?user_code=XXX  (client_id missing → auth rejected)
        # Fixed:           verification_uri?user_code=XXX&client_id=YYY
        self._user_code = self._device_flow_data["user_code"]
        self._device_verification_url = (
            self._device_flow_data["verification_uri"]
            + "?"
            + urlencode({
                "user_code": self._user_code,
                "client_id": self._client_id,
            })
        )

        _LOGGER.info("Verification URL: %s", self._device_verification_url)

        expires_in = self._device_flow_data.get("expires_in", 600)
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        return DeviceActivationStatus.PENDING

    def _check_device_activation(self) -> bool:
        """
        Poll the token endpoint once. Returns True when the user has approved.

        FIX 3: consistent form-encoded body, same as _refresh_token and _login_device_flow.
        Upstream sends params as query string without Content-Type headers.
        """
        if (
            self._expires_at is not None
            and datetime.now(timezone.utc) > self._expires_at
        ):
            raise TadoException("Device authorization expired — user took too long")

        interval = self._device_flow_data.get("interval", 5) if self._device_flow_data else 5
        time.sleep(interval)

        data = {
            "client_id":   self._client_id,
            "device_code": self._device_flow_data["device_code"],
            "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
        }

        try:
            response = self._session.request(
                "POST",
                _AUTH_URL,
                data=urlencode(data),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer":      _REFERER,
                },
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.exceptions.ConnectionError as exc:
            raise TadoException(exc) from exc

        if response.status_code == 200:
            self._set_oauth_header(response.json())
            return True

        if (
            response.status_code == 400
            and response.json().get("error") == "authorization_pending"
        ):
            _LOGGER.info("Authorization pending — waiting for user to approve")
            return False

        raise TadoException(f"Device activation failed: {response.reason}")

    def device_activation(self) -> None:
        """Block until the user approves the device flow, then mark as COMPLETED."""
        if self._device_activation_status == DeviceActivationStatus.NOT_STARTED:
            raise TadoException("Device flow has not been started")

        while True:
            if self._check_device_activation():
                break

        self._device_ready()

    def _device_ready(self) -> None:
        """Called once the token is valid — resolve home ID and API variant."""
        self._id    = self._get_id()
        self._x_api = self._check_x_line_generation()
        self._user_code               = None
        self._device_verification_url = None
        self._device_activation_status = DeviceActivationStatus.COMPLETED

    def _get_id(self) -> int:
        req = TadoRequest(action=Action.GET, domain=Domain.ME)
        me = self.request(req)
        if me.get("homes"):
            return int(me["homes"][0]["id"])
        if "homeId" in me:
            return int(me["homeId"])
        if isinstance(me.get("home"), dict):
            return int(me["home"]["id"])
        if me.get("homeIds"):
            return int(me["homeIds"][0])
        raise TadoException(f"Cannot extract home ID from /me response: {me}")

    def _check_x_line_generation(self) -> bool:
        req = TadoRequest(action=Action.GET, domain=Domain.HOME, command="")
        home = self.request(req)
        return "generation" in home and home["generation"] == "LINE_X"
