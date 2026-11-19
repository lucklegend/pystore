"""Shared test setup: a fake shop-api client and builders for the JSON it returns."""
from __future__ import annotations

from unittest.mock import create_autospec, patch

from django.contrib.messages import get_messages
from django.test import TestCase

from storefront.api import ShopApi
from storefront.cart import CART_KEY
from storefront.session import TOKEN_KEY, USER_KEY

CUSTOMER = {"id": 1, "username": "alice", "email": "alice@example.com", "is_staff": False}
STAFF = {"id": 2, "username": "sam", "email": "sam@example.com", "is_staff": True}


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
        **overrides,
    }


class StorefrontTestCase(TestCase):
    """Replaces the ShopApi the middleware builds with an autospecced mock at `self.api`."""

    def setUp(self):
        super().setUp()
        self.api = create_autospec(ShopApi, instance=True)
        self.api.list_categories.return_value = []
        self.api.list_products.return_value = page([])
        patcher = patch("storefront.middleware.ShopApi", return_value=self.api)
        self.api_class = patcher.start()
        self.addCleanup(patcher.stop)

    def log_in(self, user: dict = CUSTOMER, token: str = "secret-token") -> None:
        session = self.client.session
        session[TOKEN_KEY] = token
        session[USER_KEY] = user
        session.save()

    def fill_cart(self, lines: dict[int, int]) -> None:
        session = self.client.session
        session[CART_KEY] = {str(pk): quantity for pk, quantity in lines.items()}
        session.save()

    def cart(self) -> dict[int, int]:
        return {int(pk): quantity for pk, quantity in self.client.session.get(CART_KEY, {}).items()}

    def messages(self, response) -> list[str]:
        return [str(message) for message in get_messages(response.wsgi_request)]
