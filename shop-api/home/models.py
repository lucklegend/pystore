"""CMS page types. shop-api stores and edits them; the storefront renders them over REST."""
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page


class HomePage(Page):
    """Editor-managed landing page. The storefront adds the newest products when it renders it."""

    hero_title = models.CharField(max_length=120, default="Welcome to our shop")
    intro = RichTextField(blank=True)
    featured_count = models.PositiveSmallIntegerField(
        default=4, help_text="How many of the newest products to show. 0 hides the section."
    )

    content_panels = Page.content_panels + [
        FieldPanel("hero_title"),
        FieldPanel("intro"),
        FieldPanel("featured_count"),
    ]

    max_count = 1
    subpage_types = ["home.StandardPage"]
    preview_modes = []  # shop-api has no page templates; shop-web renders pages


class StandardPage(Page):
    """Plain content page, e.g. About, Shipping, FAQ."""

    body = RichTextField(blank=True)

    content_panels = Page.content_panels + [FieldPanel("body")]

    parent_page_types = ["home.HomePage", "home.StandardPage"]
    preview_modes = []  # shop-api has no page templates; shop-web renders pages
