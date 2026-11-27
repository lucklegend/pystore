"""Shared test setup: a fake shop-api client and builders for the JSON it returns."""
from __future__ import annotations

from unittest.mock import create_autospec, patch

from django.conf import settings
from django.contrib.messages import get_messages
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.cache import cache
from django.test import SimpleTestCase

from storefront.api import ShopApi
from storefront.cart import CART_KEY
from storefront.session import TOKEN_KEY, USER_KEY

CUSTOMER = {"id": 1, "username": "alice", "email": "alice@example.com", "is_staff": False, "full_name": ""}
STAFF = {"id": 2, "username": "sam", "email": "sam@example.com", "is_staff": True, "full_name": ""}
COUNTRIES = [{"code": "PH", "name": "Philippines"}, {"code": "SG", "name": "Singapore"}]


def product(product_id: int = 1, **overrides) -> dict:
    return {
        "id": product_id,
        "name": f"Product {product_id}",
        "description": "",
        "price": "10.00",
        "stock": 5,
        "image_url": "",
        "is_active": True,
        "category": None,
        "category_name": None,
        **overrides,
    }


def page(results: list, *, next_url: str | None = None, previous_url: str | None = None) -> dict:
    return {"count": len(results), "next": next_url, "previous": previous_url, "results": results}


def order(order_id: int = 1, **overrides) -> dict:
    return {
        "id": order_id,
        "username": "alice",
        "status": "pending",
        "created_at": "2026-01-02T03:04:05Z",
        "items": [
            {"id": 1, "product": 1, "product_name": "Product 1", "quantity": 2, "unit_price": "10.00", "subtotal": "20.00"}
        ],
        "total": "20.00",
        "shipping_address": None,
        **overrides,
    }


def address(address_id: int = 1, **overrides) -> dict:
    return {
        "id": address_id,
        "label": "home",
        "custom_label": "",
        "label_display": "Home",
        "is_default": False,
        "recipient_name": "Alice Cruz",
        "phone": "+63 912 345 6789",
        "line1": "12 Rizal Street",
        "line2": "",
        "city": "Quezon City",
        "region": "",
        "postcode": "1100",
        "country": "PH",
        "country_display": "Philippines",
        "created_at": "2026-01-02T03:04:05Z",
        "updated_at": "2026-01-02T03:04:05Z",
        **overrides,
    }


class StorefrontTestCase(SimpleTestCase):
    """Replaces the ShopApi the middleware builds with an autospecced mock at `self.api`.

    Sessions are signed cookies, so the test client does not carry one that was saved
    outside a request. The helpers below write the cookie themselves.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.api = create_autospec(ShopApi, instance=True)
        self.api.list_categories.return_value = []
        self.api.list_products.return_value = page([])
        self.api.get_cms_navigation.return_value = {"home_url": "/", "items": []}
        self.api.list_countries.return_value = COUNTRIES
        self.api.list_addresses.return_value = []
        patcher = patch("storefront.middleware.ShopApi", return_value=self.api)
        self.api_class = patcher.start()
        self.addCleanup(patcher.stop)

    def save_session(self, session: SessionStore) -> None:
        session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

    def log_in(self, user: dict = CUSTOMER, token: str = "secret-token") -> None:
        session = self.client.session
        session[TOKEN_KEY] = token
        session[USER_KEY] = user
        self.save_session(session)

    def log_out(self) -> None:
        self.save_session(SessionStore())

    def fill_cart(self, lines: dict[int, int]) -> None:
        session = self.client.session
        session[CART_KEY] = {str(pk): quantity for pk, quantity in lines.items()}
        self.save_session(session)

    def cart(self) -> dict[int, int]:
        return {int(pk): quantity for pk, quantity in self.client.session.get(CART_KEY, {}).items()}

    def messages(self, response) -> list[str]:
        return [str(message) for message in get_messages(response.wsgi_request)]
