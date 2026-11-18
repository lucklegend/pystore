from django.http import HttpRequest
from wagtail.models import Site

from .cart import Cart


def shop(request: HttpRequest) -> dict:
    site = Site.find_for_request(request)
    root = site.root_page if site else None
    return {
        "shop_user": getattr(request, "shop_user", None),
        "cart_count": Cart(request.session).count if hasattr(request, "session") else 0,
        "site_root": root,
        "nav_pages": root.get_children().live().in_menu() if root else [],
    }
