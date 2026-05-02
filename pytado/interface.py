import http.cookiejar
import json
import urllib.parse
import urllib.request


class Tado:
    """Interacts with a Tado thermostat via public API.
    Example usage: t = Tado('me@somewhere.com', 'mypasswd')
                   t.getClimate(1) # Get climate, zone 1.
    """
    headers = {'Referer': 'https://my.tado.com/'}
    api2url = 'https://my.tado.com/api/v2/homes/'

    def _apiCall(self, cmd):
        url = '%s%i/%s' % (self.api2url, self.id, cmd)
        req = urllib.request.Request(url, headers=self.headers)
        response = self.opener.open(req)
        data = json.loads(response.read())
        return data

    def _setOAuthHeader(self, data):
        access_token = data['access_token']
        self.headers['Authorization'] = 'Bearer ' + access_token

    def _loginV2(self, username, password):
        # Tado migrated OAuth infrastructure in 2024 — new endpoint is login.tado.com.
        # The grant_type=password flow still works; the body must be form-encoded.
        url = 'https://login.tado.com/oauth2/token'
        data = {
            'client_id': 'tado-webapp',
            'grant_type': 'password',
            'password': password,
            'scope': 'home.user',
            'username': username,
        }
        encoded = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={**self.headers, 'Content-Type': 'application/x-www-form-urlencoded'},
        )
        response = self.opener.open(req)
        self._setOAuthHeader(json.loads(response.read()))
        return response

    # Public interface
    def getMe(self):
        """Gets home information."""
        url = 'https://my.tado.com/api/v2/me'
        req = urllib.request.Request(url, headers=self.headers)
        response = self.opener.open(req)
        data = json.loads(response.read())
        return data

    def getState(self, zone):
        """Gets current state of Zone zone."""
        return self._apiCall('zones/%i/state' % zone)

    def getCapabilities(self, zone):
        """Gets current capabilities of Zone zone."""
        return self._apiCall('zones/%i/capabilities' % zone)

    def getClimate(self, zone):
        """Gets temp (centigrade) and humidity (% RH) for Zone zone."""
        data = self.getState(zone)['sensorDataPoints']
        return {
            'temperature': data['insideTemperature']['celsius'],
            'humidity': data['humidity']['percentage'],
        }

    def getWeather(self):
        """Gets outside weather data."""
        return self._apiCall('weather')

    def __init__(self, username, password):
        """Performs login and saves session cookie."""
        cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(),
        )
        self._loginV2(username, password)
        self.id = self.getMe()['homes'][0]['id']
