"""Admin site that lists the shop's own apps ahead of Django's built-in ones."""
from django.contrib import admin
from django.contrib.admin.apps import AdminConfig

# App labels shown first, in this order. Apps not listed keep Django's
# alphabetical order after them.
APP_ORDER = ("store",)


def app_rank(app: dict) -> int:
    label = app["app_label"]
    return APP_ORDER.index(label) if label in APP_ORDER else len(APP_ORDER)


class ShopAdminSite(admin.AdminSite):
    def get_app_list(self, request, app_label=None):
        # sorted() is stable, so unlisted apps stay alphabetical.
        return sorted(super().get_app_list(request, app_label), key=app_rank)


class ShopAdminConfig(AdminConfig):
    default_site = "config.admin_site.ShopAdminSite"
