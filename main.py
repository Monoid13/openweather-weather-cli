"""Command line entry point for the OpenWeatherMap weather CLI."""

from __future__ import annotations

import argparse
import sys

from weather import (
    UNIT_SYMBOLS,
    Cache,
    WeatherClient,
    WeatherError,
    format_report,
    get_api_key,
)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show current weather and a short 3-hour forecast "
        "from OpenWeatherMap."
    )
    parser.add_argument(
        "city",
        nargs="*",
        help='City name, e.g. "Paris" or "London,GB". Prompts if omitted.',
    )
    parser.add_argument(
        "-u", "--units",
        choices=sorted(UNIT_SYMBOLS),
        default="metric",
        help="Units of measurement (default: metric).",
    )
    parser.add_argument(
        "-n", "--count",
        type=int,
        default=8,
        help="Number of 3-hour forecast entries to show (default: 8 = 24h).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the 10-minute local cache.",
    )
    return parser.parse_args(argv)


def prompt_city(input_fn=input) -> str:
    while True:
        city = input_fn("Enter city name: ").strip()
        if city:
            return city
        print("City name cannot be empty.")


def main(argv=None, input_fn=input) -> int:
    args = parse_args(argv)
    try:
        api_key = get_api_key()
        city = " ".join(args.city).strip()
        if not city:
            city = prompt_city(input_fn)
        client = WeatherClient(
            api_key,
            units=args.units,
            cache=None if args.no_cache else Cache(),
        )
        result = client.fetch(city)
        print(format_report(result, args.units, args.count))
        return 0
    except WeatherError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
