"""Offline regressions for the existing flight-search entry point."""
import unittest
from unittest.mock import patch

from actions import flight_finder as flights


class FlightFinderTests(unittest.TestCase):
    def test_search_preserves_supported_cabins_and_defaults_unknown_cabin(self):
        for cabin in ("economy", "premium", "business", "first", "unknown"):
            with self.subTest(cabin=cabin), patch.object(
                flights, "_search_flights_browser", return_value=("", "https://example.com")
            ) as search:
                result = flights.flight_finder({
                    "origin": "CMB", "destination": "NRT", "date": "2027-01-10",
                    "return_date": "2027-01-20", "passengers": 2, "cabin": cabin,
                })
                search.assert_called_once_with(
                    "CMB", "NRT", "2027-01-10", "2027-01-20", 2,
                    "economy" if cabin == "unknown" else cabin,
                )
                self.assertIn("Could not retrieve flight data", result)

    def test_invalid_return_date_does_not_start_search(self):
        with patch.object(flights, "_search_flights_browser") as search:
            result = flights.flight_finder({
                "origin": "CMB", "destination": "NRT", "date": "2027-01-10",
                "return_date": "2027-01-09",
            })
        self.assertIn("return date must be after", result)
        search.assert_not_called()
