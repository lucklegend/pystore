from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page

from storefront.api import ApiError


class HomePage(Page):
    """Editor-managed landing page that also shows the newest products from shop-api."""

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

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["featured_products"] = []
        api = getattr(request, "shop_api", None)  # absent on some Wagtail preview requests
        if api and self.featured_count:
            try:
                data = api.list_products({"page_size": self.featured_count})
                context["featured_products"] = data["results"]
            except ApiError:
                context["shop_unavailable"] = True
        return context


class StandardPage(Page):
    """Plain content page, e.g. About, Shipping, FAQ."""

    body = RichTextField(blank=True)

    content_panels = Page.content_panels + [FieldPanel("body")]

    parent_page_types = ["home.HomePage", "home.StandardPage"]
