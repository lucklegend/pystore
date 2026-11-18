"""Session-backed cart: a map of product id → quantity. Prices always come fresh from the API."""
from __future__ import annotations

from django.contrib.sessions.backends.base import SessionBase

CART_KEY = "shop_cart"
MAX_QUANTITY = 99


class Cart:
    def __init__(self, session: SessionBase):
        self.session = session

    @property
    def lines(self) -> dict[int, int]:
        raw = self.session.get(CART_KEY, {})
        return {int(product_id): quantity for product_id, quantity in raw.items()}

    @property
    def count(self) -> int:
        return sum(self.lines.values())

    def add(self, product_id: int, quantity: int = 1) -> None:
        lines = self.lines
        self.set(product_id, lines.get(product_id, 0) + quantity)

    def set(self, product_id: int, quantity: int) -> None:
        lines = self.lines
        if quantity <= 0:
            lines.pop(product_id, None)
        else:
            lines[product_id] = min(quantity, MAX_QUANTITY)
        self._save(lines)

    def remove(self, product_id: int) -> None:
        self.set(product_id, 0)

    def keep_only(self, product_ids: set[int]) -> None:
        self._save({pk: qty for pk, qty in self.lines.items() if pk in product_ids})

    def clear(self) -> None:
        self._save({})

    def _save(self, lines: dict[int, int]) -> None:
        # JSON session serializer needs string keys.
        self.session[CART_KEY] = {str(pk): qty for pk, qty in lines.items()}
        self.session.modified = True
