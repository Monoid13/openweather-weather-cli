# openweathermap-weather-cli
Small python script to pull weather data from OpenWeatherMap API.
Shows current temperature, humidity, and a short 3-hour interval forecast.

Features
- Fetch current weather and forecast
- Retries requests if there is temporary network blip
- Simple local cache: saves results for 10 minutes, reduces API calls
- Can run interactively or pass city as command line argument
- Basic error handling for network failures and unknown cities

How to run:
Make an account on openweathermap.org and get your free API key.
Install dependencies:
`pip install -r requirements.txt`

3. Set your API key as environment variable.

On mac / linux:
export OPENWEATHER_API_KEY="your_key_here"
python main.py

Or pass city directly:
python main.py "Paris"

On windows powershell:
$env:OPENWEATHER_API_KEY="your_key_here"
python main.py "Paris"

If you run with no arguments, the program prompts you for city name interactively.

Run tests:
`pytest test_weather.py`
