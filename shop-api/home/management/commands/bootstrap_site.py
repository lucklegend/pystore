from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from wagtail.models import Page, Site

from home.models import HomePage, StandardPage

DEFAULT_PORTS = {"http": 80, "https": 443}


def site_address(url: str) -> tuple[str, int]:
    """The hostname and port a Wagtail Site needs so its page URLs point at `url`."""
    parts = urlsplit(url)
    return parts.hostname or "localhost", parts.port or DEFAULT_PORTS.get(parts.scheme, 80)


class Command(BaseCommand):
    help = "Replace Wagtail's placeholder page with a HomePage and an About page. Safe to run more than once."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        if HomePage.objects.exists():
            self.stdout.write("Site already bootstrapped; nothing to do.")
            return

        # Wagtail's initial migration creates a plain "Welcome" Page; remove it (and its Site).
        for child in Page.get_first_root_node().get_children():
            if child.specific_class is Page:
                child.delete()

        root = Page.get_first_root_node()  # re-fetch: the tree changed
        home = root.add_child(
            instance=HomePage(
                title="Home",
                slug="home",
                hero_title=f"Welcome to {settings.WAGTAIL_SITE_NAME}",
                intro="<p>Everyday goods, picked with care. Edit this text in the CMS at /cms/.</p>",
            )
        )
        home.add_child(
            instance=StandardPage(
                title="About",
                slug="about",
                show_in_menus=True,
                body="<p>This page is managed in Wagtail. Products come from the shop API.</p>",
            )
        )
        # The storefront serves the pages, so the Site carries its host and "View live" opens it.
        hostname, port = site_address(settings.STOREFRONT_URL)
        Site.objects.update_or_create(
            is_default_site=True,
            defaults={
                "hostname": hostname,
                "port": port,
                "site_name": settings.WAGTAIL_SITE_NAME,
                "root_page": home,
            },
        )
        self.stdout.write(self.style.SUCCESS("Created HomePage and About page."))
