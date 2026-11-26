"""Serve CMS pages from shop-api's content API, one template per page type."""
from __future__ import annotations

import logging
from typing import Callable, NamedTuple

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse, HttpResponsePermanentRedirect, HttpResponseRedirect
from django.shortcuts import render

from storefront.api import ApiError, ShopApi

from .cms import resolve_page

logger = logging.getLogger(__name__)


class Renderer(NamedTuple):
    template: str
    build_context: Callable[[ShopApi, dict], dict]


def home_page_context(api: ShopApi, page: dict) -> dict:
    """The newest products, as many as the editor asked for. 0 hides the section."""
    count = page["fields"]["featured_count"]
    if not count:
        return {"featured_products": []}
    try:
        return {"featured_products": api.list_products({"page_size": count})["results"]}
    except ApiError:
        return {"featured_products": [], "shop_unavailable": True}


def no_extra_context(api: ShopApi, page: dict) -> dict:
    return {}


RENDERERS = {
    "home.HomePage": Renderer("home/home_page.html", home_page_context),
    "home.StandardPage": Renderer("home/standard_page.html", no_extra_context),
}


def cms_page(request: HttpRequest, path: str) -> HttpResponse:
    payload = resolve_page(request.public_api, cache, f"/{path}", settings.CMS_CACHE_SECONDS)
    if payload["kind"] == "redirect":
        response_class = HttpResponsePermanentRedirect if payload["permanent"] else HttpResponseRedirect
        return response_class(payload["location"])

    page = payload["page"]
    renderer = RENDERERS.get(page["type"])
    if renderer is None:
        logger.warning("No renderer for CMS page type %r at %s", page["type"], page["url"])
        raise Http404("Unknown page type.")
    context = {"page": page, **renderer.build_context(request.public_api, page)}
    return render(request, renderer.template, context)
