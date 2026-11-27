from unittest.mock import Mock

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase

from storefront.api import ApiError
from storefront.countries import COUNTRIES_CACHE_KEY, COUNTRIES_TTL, country_choices

COUNTRIES = [{"code": "PH", "name": "Philippines"}, {"code": "SG", "name": "Singapore"}]


class CountryChoicesTests(SimpleTestCase):
    def setUp(self):
        self.cache = LocMemCache("country-tests", {})
        self.addCleanup(self.cache.clear)
        self.api = Mock()

    def test_returns_code_and_name_pairs(self):
        self.api.list_countries.return_value = COUNTRIES

        self.assertEqual(country_choices(self.api, self.cache), [("PH", "Philippines"), ("SG", "Singapore")])

    def test_the_second_call_is_served_from_the_cache(self):
        self.api.list_countries.return_value = COUNTRIES

        country_choices(self.api, self.cache)
        country_choices(self.api, self.cache)

        self.api.list_countries.assert_called_once_with()
        self.assertEqual(self.cache.get(COUNTRIES_CACHE_KEY), COUNTRIES)
        self.assertEqual(COUNTRIES_TTL, 86400)

    def test_an_api_error_propagates_and_is_not_cached(self):
        self.api.list_countries.side_effect = [ApiError(503, {}), COUNTRIES]

        with self.assertRaises(ApiError):
            country_choices(self.api, self.cache)
        self.assertIsNone(self.cache.get(COUNTRIES_CACHE_KEY))

        self.assertEqual(country_choices(self.api, self.cache)[0], ("PH", "Philippines"))
