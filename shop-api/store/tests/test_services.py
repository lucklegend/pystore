from decimal import Decimal

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from store.models import Order, Product
from store.services import cancel_order, place_order

from .factories import make_order, make_product, make_user


def item_errors(error: ValidationError) -> list[str]:
    return [str(message) for message in error.detail["items"]]


class PlaceOrderTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_creates_pending_order_and_reserves_stock(self):
        tea = make_product("Tea", price="4.00", stock=10)
        mug = make_product("Mug", price="12.50", stock=3)

        order = place_order(self.user, [(tea.pk, 2), (mug.pk, 3)])

        self.assertEqual(order.user, self.user)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual({item.product_id: item.quantity for item in order.items.all()}, {tea.pk: 2, mug.pk: 3})
        tea.refresh_from_db()
        mug.refresh_from_db()
        self.assertEqual(tea.stock, 8)
        self.assertEqual(mug.stock, 0)

    def test_copies_current_price_onto_each_item(self):
        product = make_product(price="7.25")

        order = place_order(self.user, [(product.pk, 1)])

        self.assertEqual(order.items.get().unit_price, Decimal("7.25"))

    def test_merges_repeated_lines_for_the_same_product(self):
        product = make_product(stock=10)

        order = place_order(self.user, [(product.pk, 2), (product.pk, 3)])

        item = order.items.get()
        self.assertEqual(item.quantity, 5)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)

    def test_merged_lines_are_checked_against_stock_together(self):
        product = make_product("Tea", stock=4)

        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [(product.pk, 3), (product.pk, 2)])

        self.assertEqual(item_errors(caught.exception), ["Only 4 of 'Tea' left in stock."])

    def test_rejects_an_empty_order(self):
        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [])

        self.assertEqual(item_errors(caught.exception), ["An order needs at least one item."])
        self.assertFalse(Order.objects.exists())

    def test_rejects_unknown_and_inactive_products(self):
        hidden = make_product(is_active=False)
        available = make_product()

        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [(available.pk, 1), (hidden.pk, 1), (99999, 1)])

        self.assertEqual(
            item_errors(caught.exception),
            [f"Product {hidden.pk} is not available.", "Product 99999 is not available."],
        )

    def test_short_stock_lists_every_short_product_and_changes_nothing(self):
        tea = make_product("Tea", stock=1)
        mug = make_product("Mug", stock=0)
        plenty = make_product("Plenty", stock=50)

        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [(tea.pk, 2), (mug.pk, 1), (plenty.pk, 1)])

        self.assertCountEqual(
            item_errors(caught.exception),
            ["Only 1 of 'Tea' left in stock.", "No Mug left in the stock."],
        )
        self.assertFalse(Order.objects.exists())
        self.assertEqual(Product.objects.get(pk=plenty.pk).stock, 50)

    def test_ordering_exactly_the_remaining_stock_succeeds(self):
        product = make_product(stock=2)

        place_order(self.user, [(product.pk, 2)])

        product.refresh_from_db()
        self.assertEqual(product.stock, 0)


class CancelOrderTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_cancels_pending_order_and_returns_stock(self):
        tea = make_product(stock=10)
        mug = make_product(stock=5)
        order = place_order(self.user, [(tea.pk, 4), (mug.pk, 5)])

        cancelled = cancel_order(order)

        self.assertEqual(cancelled.status, Order.Status.CANCELLED)
        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.CANCELLED)
        self.assertEqual(Product.objects.get(pk=tea.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=mug.pk).stock, 5)

    def test_reads_the_current_status_not_the_stale_instance(self):
        product = make_product(stock=10)
        order = place_order(self.user, [(product.pk, 1)])
        Order.objects.filter(pk=order.pk).update(status=Order.Status.PAID)

        with self.assertRaises(ValidationError):
            cancel_order(order)  # `order` in memory still says pending

        self.assertEqual(Product.objects.get(pk=product.pk).stock, 9)

    def test_rejects_orders_that_are_not_pending(self):
        product = make_product(stock=10)
        for status in (Order.Status.PAID, Order.Status.SHIPPED, Order.Status.CANCELLED):
            with self.subTest(status=status):
                order = make_order(self.user, [(product, 1)], status=status)

                with self.assertRaises(ValidationError) as caught:
                    cancel_order(order)

                self.assertEqual(str(caught.exception.detail["detail"]), "Only pending orders can be cancelled.")
                self.assertEqual(Product.objects.get(pk=product.pk).stock, 10)

    def test_cancelling_twice_does_not_return_stock_twice(self):
        product = make_product(stock=10)
        order = place_order(self.user, [(product.pk, 3)])
        cancel_order(order)

        with self.assertRaises(ValidationError):
            cancel_order(order)

        self.assertEqual(Product.objects.get(pk=product.pk).stock, 10)
