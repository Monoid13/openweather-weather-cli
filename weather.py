"""Core logic for fetching and formatting weather data from OpenWeatherMap."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://api.openweathermap.org/data/2.5"
API_KEY_ENV = "OPENWEATHER_API_KEY"
DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_CACHE_TTL = 10 * 60  # 10 minutes
DEFAULT_CACHE_PATH = Path.home() / ".cache" / "openweather-cli" / "cache.json"

UNIT_SYMBOLS = {
    "metric": ("°C", "m/s"),
    "imperial": ("°F", "mph"),
    "standard": ("K", "m/s"),
}


class WeatherError(Exception):
    """Base error for anything that goes wrong fetching weather."""


class CityNotFoundError(WeatherError):
    """Raised when OpenWeatherMap does not know the requested city."""


class APIKeyError(WeatherError):
    """Raised when the API key is missing or rejected."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def get_api_key(env: Optional[dict] = None) -> str:
    env = os.environ if env is None else env
    key = (env.get(API_KEY_ENV) or "").strip()
    if not key:
        raise APIKeyError(
            f"No API key found. Set the {API_KEY_ENV} environment variable "
            "(get a free key at https://openweathermap.org)."
        )
    return key


# --------------------------------------------------------------------------- #
# HTTP session with retries
# --------------------------------------------------------------------------- #
def build_session(retries: int = 3, backoff: float = 0.5) -> requests.Session:
    """Session that retries transient failures (connection errors, 429, 5xx)."""
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
class Cache:
    """Tiny JSON file cache with a time-to-live per entry."""

    def __init__(
        self,
        path: Path | str = DEFAULT_CACHE_PATH,
        ttl: int = DEFAULT_CACHE_TTL,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.ttl = ttl
        self.clock = clock

    @staticmethod
    def make_key(*parts: Any) -> str:
        raw = "|".join(str(p).strip().lower() for p in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load(self) -> dict:
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, self.path)
        except OSError:
            # Caching is best-effort; never fail the request because of it.
            pass

    def get(self, key: str) -> Optional[Any]:
        entry = self._load().get(key)
        if not isinstance(entry, dict) or "ts" not in entry:
            return None
        if self.clock() - entry["ts"] > self.ttl:
            return None
        return entry.get("value")

    def set(self, key: str, value: Any) -> None:
        now = self.clock()
        data = {
            k: v
            for k, v in self._load().items()
            if isinstance(v, dict) and now - v.get("ts", 0) <= self.ttl
        }
        data[key] = {"ts": now, "value": value}
        self._save(data)


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #
class WeatherClient:
    def __init__(
        self,
        api_key: str,
        units: str = "metric",
        session: Optional[requests.Session] = None,
        cache: Optional[Cache] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if units not in UNIT_SYMBOLS:
            raise ValueError(f"units must be one of {sorted(UNIT_SYMBOLS)}")
        self.api_key = api_key
        self.units = units
        self.session = session or build_session()
        self.cache = cache
        self.timeout = timeout

    def _get(self, endpoint: str, city: str) -> dict:
        params = {"q": city, "appid": self.api_key, "units": self.units}
        try:
            resp = self.session.get(
                f"{BASE_URL}/{endpoint}", params=params, timeout=self.timeout
            )
        except requests.exceptions.Timeout as exc:
            raise WeatherError("The request to OpenWeatherMap timed out.") from exc
        except requests.exceptions.RequestException as exc:
            raise WeatherError(
                "Could not reach OpenWeatherMap. Check your internet connection."
            ) from exc

        if resp.status_code == 401:
            raise APIKeyError("OpenWeatherMap rejected the API key (401). "
                              "New keys can take a couple of hours to activate.")
        if resp.status_code == 404:
            raise CityNotFoundError(f"City not found: {city!r}")
        if resp.status_code == 429:
            raise WeatherError("Rate limit exceeded. Please try again later.")
        if not resp.ok:
            raise WeatherError(
                f"OpenWeatherMap returned an error (HTTP {resp.status_code})."
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise WeatherError("Received an invalid response from OpenWeatherMap.") from exc

    def fetch(self, city: str) -> dict:
        """Return {'current': ..., 'forecast': ...} raw API payloads for a city."""
        city = (city or "").strip()
        if not city:
            raise CityNotFoundError("City name must not be empty.")

        key = Cache.make_key(city, self.units)
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        result = {
            "current": self._get("weather", city),
            "forecast": self._get("forecast", city),
        }
        if self.cache is not None:
            self.cache.set(key, result)
        return result


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def _local_time(ts: int, tz_offset: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone(timedelta(seconds=tz_offset)))


def _describe(entry: dict) -> str:
    weather = entry.get("weather") or [{}]
    return str(weather[0].get("description", "")).capitalize()


def format_current(data: dict, units: str = "metric") -> str:
    temp_u, wind_u = UNIT_SYMBOLS[units]
    main = data.get("main", {})
    name = data.get("name", "Unknown")
    country = data.get("sys", {}).get("country")
    place = f"{name}, {country}" if country else name
    lines = [
        f"Current weather in {place}",
        f"  {_describe(data)}",
        f"  Temperature: {main.get('temp', float('nan')):.1f}{temp_u} "
        f"(feels like {main.get('feels_like', float('nan')):.1f}{temp_u})",
        f"  Humidity:    {main.get('humidity', '?')}%",
    ]
    wind = data.get("wind", {})
    if "speed" in wind:
        lines.append(f"  Wind:        {wind['speed']:.1f} {wind_u}")
    return "\n".join(lines)


def format_forecast(data: dict, units: str = "metric", count: int = 8) -> str:
    temp_u, _ = UNIT_SYMBOLS[units]
    tz_offset = data.get("city", {}).get("timezone", 0)
    entries = (data.get("list") or [])[: max(count, 0)]
    if not entries:
        return "No forecast data available."
    lines = ["Forecast (3-hour intervals, local time)"]
    for entry in entries:
        when = _local_time(entry["dt"], tz_offset).strftime("%a %H:%M")
        main = entry.get("main", {})
        pop = entry.get("pop")
        rain = f"  {round(pop * 100):>3}% rain" if pop is not None else ""
        lines.append(
            f"  {when}  {main.get('temp', float('nan')):6.1f}{temp_u}  "
            f"{main.get('humidity', '?'):>3}%  {_describe(entry)}{rain}"
        )
    return "\n".join(lines)


def format_report(result: dict, units: str = "metric", count: int = 8) -> str:
    return (
        format_current(result["current"], units)
        + "\n\n"
        + format_forecast(result["forecast"], units, count)
    )
