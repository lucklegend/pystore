"""Small builders for test data, so each test states only the fields it cares about."""
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model

from config.fixture_secrets import USER_PASSWORD

from store.models import Category, Order, OrderItem, Product

_sequence = count(1)


def make_user(username: str | None = None, *, is_staff: bool = False, password: str = USER_PASSWORD):
    name = username or f"user{next(_sequence)}"
    return get_user_model().objects.create_user(
        username=name, email=f"{name}@example.com", password=password, is_staff=is_staff
    )


def make_category(name: str | None = None) -> Category:
    return Category.objects.create(name=name or f"Category {next(_sequence)}")


def make_product(
    name: str | None = None,
    *,
    price: str = "10.00",
    stock: int = 10,
    is_active: bool = True,
    category: Category | None = None,
    description: str = "",
) -> Product:
    return Product.objects.create(
        name=name or f"Product {next(_sequence)}",
        price=Decimal(price),
        stock=stock,
        is_active=is_active,
        category=category,
        description=description,
    )


def make_order(user, items: list[tuple[Product, int]], *, status: str = Order.Status.PENDING) -> Order:
    """Build an order directly, bypassing stock reservation."""
    order = Order.objects.create(user=user, status=status)
    for product, quantity in items:
        OrderItem.objects.create(order=order, product=product, quantity=quantity, unit_price=product.price)
    return order
