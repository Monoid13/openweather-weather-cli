# openweathermap-weather-cli
Small python script to pull weather data from OpenWeatherMap API.
Shows current temperature, humidity, and a short 3-hour interval forecast.

## Features
- Fetch current weather and forecast
- Retries requests if there is temporary network blip (connection errors, 429 and 5xx, with backoff)
- Simple local cache: saves results for 10 minutes, reduces API calls
  (stored in `~/.cache/openweather-cli/cache.json`)
- Can run interactively or pass city as command line argument
- Basic error handling for network failures, invalid API keys and unknown cities

## Project layout
- `weather.py` – API client, retry session, cache and output formatting
- `main.py` – command line interface
- `test_weather.py` – tests (no network access needed)

## How to run
1. Make an account on openweathermap.org and get your free API key.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Set your API key as environment variable.

On mac / linux:
```
export OPENWEATHER_API_KEY="your_key_here"
python main.py
```

Or pass city directly:
```
python main.py "Paris"
python main.py New York
python main.py "London,GB" --units imperial --count 4
```

On windows powershell:
```
$env:OPENWEATHER_API_KEY="your_key_here"
python main.py "Paris"
```

If you run with no arguments, the program prompts you for city name interactively.

### Options
| Option | Description |
| --- | --- |
| `-u`, `--units` | `metric` (default), `imperial` or `standard` (Kelvin) |
| `-n`, `--count` | Number of 3-hour forecast entries to show (default 8 = 24 hours) |
| `--no-cache` | Skip the 10-minute cache and always call the API |

### Example output
```
Current weather in Paris, FR
  Light rain
  Temperature: 12.3°C (feels like 10.0°C)
  Humidity:    81%
  Wind:        4.1 m/s

Forecast (3-hour intervals, local time)
  Tue 23:13    10.0°C   70%  Clouds   25% rain
  Wed 02:13    11.0°C   71%  Clouds   25% rain
```

The program exits with status 0 on success and 1 on error.

## Run tests
`pytest test_weather.py`
