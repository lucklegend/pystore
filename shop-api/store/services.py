"""Order placement and cancellation, kept out of the views so stock rules live in one place."""
from collections import Counter
from typing import Iterable, Tuple

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import DeliveryAddress, Order, OrderItem, Product

OrderLine = Tuple[int, int]  # (product_id, quantity)


def place_order(user, lines: Iterable[OrderLine], address_id: int | None) -> Order:
    """Create a pending order shipping to one of the user's addresses and reserve stock.

    Raises ValidationError if the address is missing or not the user's, or if stock runs short.
    """
    quantities = Counter()
    for product_id, quantity in lines:
        quantities[product_id] += quantity
    if not quantities:
        raise ValidationError({"items": ["An order needs at least one item."]})
    # this will check the database for stock availability and reserve it in a transaction
    with transaction.atomic():
        # Scoped to the user, staff included, so nobody can ship to someone else's address.
        # A missing id and a foreign one get the same message, so ids cannot be probed.
        address = None
        if address_id is not None:
            address = DeliveryAddress.objects.filter(pk=address_id, user=user).first()
        if address is None:
            raise ValidationError({"delivery_address": ["Choose one of your delivery addresses."]})

        products = Product.objects.select_for_update().filter(pk__in=quantities, is_active=True)
        by_id = {product.pk: product for product in products}

        missing = set(quantities) - set(by_id)
        if missing:
            raise ValidationError({"items": [f"Product {pk} is not available." for pk in sorted(missing)]})

        short = [
            stock_shortage_message(by_id[pk])
            for pk, quantity in quantities.items()
            if by_id[pk].stock < quantity
        ]
        if short:
            raise ValidationError({"items": short})

        order = Order.objects.create(user=user, **address.snapshot_fields())
        for pk, quantity in quantities.items():
            product = by_id[pk]
            OrderItem.objects.create(order=order, product=product, quantity=quantity, unit_price=product.price)
            product.stock -= quantity
            product.save(update_fields=["stock", "updated_at"])
    return order


def stock_shortage_message(product: Product) -> str:
    if product.stock == 0:
        return f"No {product.name} left in the stock."
    return f"Only {product.stock} of '{product.name}' left in stock."


def cancel_order(order: Order) -> Order:
    """Cancel a pending order and return its stock."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.PENDING:
            raise ValidationError({"detail": "Only pending orders can be cancelled."})
        for item in order.items.select_related("product"):
            product = Product.objects.select_for_update().get(pk=item.product_id)
            product.stock += item.quantity
            product.save(update_fields=["stock", "updated_at"])
        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status"])
    return order
