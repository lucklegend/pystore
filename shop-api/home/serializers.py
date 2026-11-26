"""JSON shapes of CMS pages and navigation for the storefront.

Rich text leaves here already expanded, so shop-web renders it as it is. URLs are relative to
the default Site, which is the storefront host.
"""
from collections.abc import Callable, Mapping
from typing import Any

from wagtail.models import Page, Site
from wagtail.rich_text import expand_db_html

from .models import HomePage, StandardPage

FieldsBuilder = Callable[[Any], dict[str, object]]


def page_path(page: Page) -> str:
    _, _, path = page.get_url_parts()
    return path


def home_page_fields(page: HomePage) -> dict[str, object]:
    return {
        "hero_title": page.hero_title,
        "intro_html": expand_db_html(page.intro),
        "featured_count": page.featured_count,
    }


def standard_page_fields(page: StandardPage) -> dict[str, object]:
    return {"body_html": expand_db_html(page.body)}


# Keyed by the page type the storefront sees. A new page type needs an entry here
# and a renderer in shop-web.
PAGE_FIELDS: dict[str, FieldsBuilder] = {
    "home.HomePage": home_page_fields,
    "home.StandardPage": standard_page_fields,
}


def page_payload(page: Page, fields_by_type: Mapping[str, FieldsBuilder]) -> dict[str, object]:
    """`page` must be the specific instance, as `Page.route` returns it."""
    page_type = page._meta.label
    return {
        "id": page.pk,
        "type": page_type,
        "title": page.title,
        "seo_title": page.seo_title,
        "search_description": page.search_description,
        "url": page_path(page),
        "fields": fields_by_type[page_type](page),
    }


def navigation_payload(site: Site) -> dict[str, object]:
    menu = site.root_page.get_children().live().public().in_menu()
    return {
        "home_url": page_path(site.root_page),
        "items": [{"id": page.pk, "title": page.title, "url": page_path(page)} for page in menu],
    }
