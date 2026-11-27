"""The country list for address forms, read from shop-api so both projects share one source.

Only successful payloads are cached. An ApiError reaches the caller on every request,
so an outage ends as soon as shop-api is back rather than after the TTL.
"""
from __future__ import annotations

from django.core.cache import cache as default_cache
from django.core.cache.backends.base import BaseCache

from .api import ShopApi

COUNTRIES_CACHE_KEY = "shop-api:countries"
COUNTRIES_TTL = 86400


def country_choices(api: ShopApi, cache: BaseCache = default_cache) -> list[tuple[str, str]]:
    """(code, name) pairs in the API's order. ApiError propagates."""
    countries = cache.get(COUNTRIES_CACHE_KEY)
    if countries is None:
        countries = api.list_countries()
        cache.set(COUNTRIES_CACHE_KEY, countries, COUNTRIES_TTL)
    return [(country["code"], country["name"]) for country in countries]
