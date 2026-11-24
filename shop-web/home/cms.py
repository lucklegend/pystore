"""CMS content from shop-api, cached so a page view does not cost a round trip every time.

Only successful payloads are cached. Errors reach the caller on every request, so an
outage ends as soon as shop-api is back rather than after the TTL.
"""
from __future__ import annotations

import hashlib

from django.core.cache.backends.base import BaseCache

from storefront.api import ApiError, ShopApi

EMPTY_NAVIGATION = {"home_url": "/", "items": []}


def page_cache_key(path: str) -> str:
    # The path comes from the URL, so hash it to keep the key short and free of odd characters.
    return f"cms:page:{hashlib.sha256(path.encode()).hexdigest()}"


def resolve_page(api: ShopApi, cache: BaseCache, path: str, ttl: int) -> dict:
    """The page or redirect payload for `path`. ApiError (404, 503, ...) propagates."""
    key = page_cache_key(path)
    payload = cache.get(key)
    if payload is None:
        payload = api.get_cms_page(path)
        cache.set(key, payload, ttl)
    return payload


def navigation(api: ShopApi, cache: BaseCache, ttl: int) -> dict:
    """The site root URL and its menu pages, or an empty menu when shop-api can't be reached."""
    payload = cache.get("cms:navigation")
    if payload is None:
        try:
            payload = api.get_cms_navigation()
        except ApiError:
            return EMPTY_NAVIGATION
        cache.set("cms:navigation", payload, ttl)
    return payload
