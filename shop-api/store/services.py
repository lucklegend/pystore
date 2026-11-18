"""Order placement and cancellation, kept out of the views so stock rules live in one place."""
from collections import Counter
from typing import Iterable, Tuple

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Order, OrderItem, Product

OrderLine = Tuple[int, int]  # (product_id, quantity)


def place_order(user, lines: Iterable[OrderLine]) -> Order:
    """Create a pending order and reserve stock. Raises ValidationError if stock runs short."""
    quantities = Counter()
    for product_id, quantity in lines:
        quantities[product_id] += quantity
    if not quantities:
        raise ValidationError({"items": ["An order needs at least one item."]})

    with transaction.atomic():
        products = Product.objects.select_for_update().filter(pk__in=quantities, is_active=True)
        by_id = {product.pk: product for product in products}

        missing = set(quantities) - set(by_id)
        if missing:
            raise ValidationError({"items": [f"Product {pk} is not available." for pk in sorted(missing)]})

        short = [
            f"Only {by_id[pk].stock} of '{by_id[pk].name}' left in stock."
            for pk, quantity in quantities.items()
            if by_id[pk].stock < quantity
        ]
        if short:
            raise ValidationError({"items": short})

        order = Order.objects.create(user=user)
        for pk, quantity in quantities.items():
            product = by_id[pk]
            OrderItem.objects.create(order=order, product=product, quantity=quantity, unit_price=product.price)
            product.stock -= quantity
            product.save(update_fields=["stock", "updated_at"])
    return order


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
