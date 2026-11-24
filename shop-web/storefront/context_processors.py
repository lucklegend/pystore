from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

from home.cms import EMPTY_NAVIGATION, navigation

from .cart import Cart


def shop(request: HttpRequest) -> dict:
    api = getattr(request, "shop_api", None)
    menu = navigation(api, cache, settings.CMS_CACHE_SECONDS) if api else EMPTY_NAVIGATION
    return {
        "shop_user": getattr(request, "shop_user", None),
        "cart_count": Cart(request.session).count if hasattr(request, "session") else 0,
        "site_url": menu["home_url"],
        "nav_pages": menu["items"],
        "cms_url": f"{settings.SHOP_API_PUBLIC_URL}/cms/",
    }
