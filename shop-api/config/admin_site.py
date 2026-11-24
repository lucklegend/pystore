"""Admin site for shop-api.

- Lists the shop's own apps ahead of Django's built-in ones.
"""
from functools import partial

from django.contrib import admin
from django.contrib.admin.apps import AdminConfig
from django.db.models.base import ModelBase
from django.utils.translation import gettext_lazy as _

from config.admin_per_page import per_page_changelist

# App labels shown first, in this order. Apps not listed keep Django's
# alphabetical order after them.
APP_ORDER = ("store",)

SELECT_ACTION_CHOICE = [("", _("Select action"))]


def app_rank(app: dict) -> int:
    label = app["app_label"]
    return APP_ORDER.index(label) if label in APP_ORDER else len(APP_ORDER)


def prompt_select_action(model_admin: admin.ModelAdmin) -> None:
    get_choices = type(model_admin).get_action_choices
    model_admin.get_action_choices = partial(get_choices, model_admin, default_choices=SELECT_ACTION_CHOICE)


class ShopAdminSite(admin.AdminSite):
    def get_app_list(self, request, app_label=None):
        # sorted() is stable, so unlisted apps stay alphabetical.
        return sorted(super().get_app_list(request, app_label), key=app_rank)

    def register(self, model_or_iterable, admin_class=None, **options):
        super().register(model_or_iterable, admin_class, **options)
        models = [model_or_iterable] if isinstance(model_or_iterable, ModelBase) else model_or_iterable
        for model in models:
            model_admin = self.get_model_admin(model)
            prompt_select_action(model_admin)
            model_admin.get_changelist = per_page_changelist


class ShopAdminConfig(AdminConfig):
    default_site = "config.admin_site.ShopAdminSite"
