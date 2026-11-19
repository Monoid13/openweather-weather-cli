"""Tests for the weather CLI. No network access required."""

from unittest import mock

import pytest
import requests

import main
import weather
from weather import (
    APIKeyError,
    Cache,
    CityNotFoundError,
    WeatherClient,
    WeatherError,
)

CURRENT = {
    "name": "Paris",
    "sys": {"country": "FR"},
    "weather": [{"description": "light rain"}],
    "main": {"temp": 12.34, "feels_like": 10.0, "humidity": 81},
    "wind": {"speed": 4.1},
}
FORECAST = {
    "city": {"timezone": 3600},
    "list": [
        {
            "dt": 1700000000 + i * 10800,
            "main": {"temp": 10 + i, "humidity": 70 + i},
            "weather": [{"description": "clouds"}],
            "pop": 0.25,
        }
        for i in range(10)
    ],
}


def make_response(status=200, payload=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.ok = 200 <= status < 400
    resp.json.return_value = payload
    return resp


def make_session(*responses):
    session = mock.Mock()
    session.get.side_effect = list(responses)
    return session


# --------------------------------------------------------------------------- #
# API key
# --------------------------------------------------------------------------- #
def test_get_api_key_present():
    assert weather.get_api_key({"OPENWEATHER_API_KEY": " abc "}) == "abc"


def test_get_api_key_missing():
    with pytest.raises(APIKeyError):
        weather.get_api_key({})


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
def test_fetch_success_calls_both_endpoints():
    session = make_session(make_response(200, CURRENT), make_response(200, FORECAST))
    client = WeatherClient("key", session=session)
    result = client.fetch("Paris")
    assert result == {"current": CURRENT, "forecast": FORECAST}
    urls = [c.args[0] for c in session.get.call_args_list]
    assert urls[0].endswith("/weather") and urls[1].endswith("/forecast")
    params = session.get.call_args_list[0].kwargs["params"]
    assert params == {"q": "Paris", "appid": "key", "units": "metric"}


def test_fetch_unknown_city():
    client = WeatherClient("key", session=make_session(make_response(404)))
    with pytest.raises(CityNotFoundError):
        client.fetch("Atlantis")


def test_fetch_empty_city():
    with pytest.raises(CityNotFoundError):
        WeatherClient("key", session=make_session()).fetch("   ")


def test_fetch_bad_api_key():
    client = WeatherClient("bad", session=make_session(make_response(401)))
    with pytest.raises(APIKeyError):
        client.fetch("Paris")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_fetch_server_errors(status):
    client = WeatherClient("key", session=make_session(make_response(status)))
    with pytest.raises(WeatherError):
        client.fetch("Paris")


@pytest.mark.parametrize(
    "exc", [requests.exceptions.ConnectionError(), requests.exceptions.Timeout()]
)
def test_fetch_network_failure(exc):
    client = WeatherClient("key", session=make_session(exc))
    with pytest.raises(WeatherError):
        client.fetch("Paris")


def test_fetch_invalid_json():
    resp = make_response(200)
    resp.json.side_effect = ValueError("bad json")
    client = WeatherClient("key", session=make_session(resp))
    with pytest.raises(WeatherError):
        client.fetch("Paris")


def test_invalid_units():
    with pytest.raises(ValueError):
        WeatherClient("key", units="kelvinish", session=make_session())


def test_session_has_retry_adapter():
    session = weather.build_session(retries=4)
    adapter = session.get_adapter("https://api.openweathermap.org")
    assert adapter.max_retries.total == 4
    assert 503 in adapter.max_retries.status_forcelist


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_cache_hit_and_expiry(tmp_path):
    clock = FakeClock()
    cache = Cache(tmp_path / "c.json", ttl=600, clock=clock)
    cache.set("k", {"a": 1})
    assert cache.get("k") == {"a": 1}
    clock.t += 599
    assert cache.get("k") == {"a": 1}
    clock.t += 2
    assert cache.get("k") is None


def test_cache_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("not json")
    cache = Cache(path)
    assert cache.get("k") is None
    cache.set("k", 1)
    assert cache.get("k") == 1


def test_cache_key_normalises_city():
    assert Cache.make_key(" Paris ", "metric") == Cache.make_key("paris", "metric")
    assert Cache.make_key("paris", "metric") != Cache.make_key("paris", "imperial")


def test_client_uses_cache(tmp_path):
    clock = FakeClock()
    cache = Cache(tmp_path / "c.json", clock=clock)
    session = make_session(
        make_response(200, CURRENT), make_response(200, FORECAST),
        make_response(200, CURRENT), make_response(200, FORECAST),
    )
    client = WeatherClient("key", session=session, cache=cache)
    client.fetch("Paris")
    client.fetch("paris")
    assert session.get.call_count == 2  # second call served from cache
    clock.t += 601
    client.fetch("Paris")
    assert session.get.call_count == 4  # cache expired


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def test_format_current():
    out = weather.format_current(CURRENT)
    assert "Paris, FR" in out
    assert "Light rain" in out
    assert "12.3°C" in out
    assert "81%" in out
    assert "4.1 m/s" in out


def test_format_current_imperial():
    out = weather.format_current(CURRENT, "imperial")
    assert "°F" in out and "mph" in out


def test_format_forecast_limits_count_and_uses_local_time():
    out = weather.format_forecast(FORECAST, count=3)
    lines = out.splitlines()
    assert len(lines) == 4  # header + 3 entries
    # 1700000000 is Tue 22:13 UTC -> 23:13 at UTC+1
    assert "Tue 23:13" in lines[1]
    assert "25% rain" in lines[1]


def test_format_forecast_empty():
    assert "No forecast" in weather.format_forecast({"list": []})


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_client(monkeypatch):
    instance = mock.Mock()
    instance.fetch.return_value = {"current": CURRENT, "forecast": FORECAST}
    cls = mock.Mock(return_value=instance)
    monkeypatch.setattr(main, "WeatherClient", cls)
    monkeypatch.setenv("OPENWEATHER_API_KEY", "key")
    return cls, instance


def test_cli_city_argument(fake_client, capsys):
    cls, instance = fake_client
    assert main.main(["New", "York", "--no-cache"]) == 0
    instance.fetch.assert_called_once_with("New York")
    assert cls.call_args.kwargs["cache"] is None
    assert "Current weather in Paris" in capsys.readouterr().out


def test_cli_interactive_prompt(fake_client):
    _, instance = fake_client
    answers = iter(["", "Berlin"])
    assert main.main(["--no-cache"], input_fn=lambda _: next(answers)) == 0
    instance.fetch.assert_called_once_with("Berlin")


def test_cli_missing_api_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    assert main.main(["Paris"]) == 1
    assert "OPENWEATHER_API_KEY" in capsys.readouterr().err


def test_cli_reports_errors(fake_client, capsys):
    _, instance = fake_client
    instance.fetch.side_effect = CityNotFoundError("City not found: 'Atlantis'")
    assert main.main(["Atlantis", "--no-cache"]) == 1
    assert "City not found" in capsys.readouterr().err
