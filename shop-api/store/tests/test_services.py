from decimal import Decimal

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from store.models import Order, Product
from store.services import cancel_order, place_order

from .factories import make_address, make_order, make_product, make_user


def item_errors(error: ValidationError) -> list[str]:
    return [str(message) for message in error.detail["items"]]


def address_errors(error: ValidationError) -> list[str]:
    return [str(message) for message in error.detail["delivery_address"]]


class PlaceOrderTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.address = make_address(self.user)

    def test_creates_pending_order_and_reserves_stock(self):
        tea = make_product("Tea", price="4.00", stock=10)
        mug = make_product("Mug", price="12.50", stock=3)

        order = place_order(self.user, [(tea.pk, 2), (mug.pk, 3)], self.address.pk)

        self.assertEqual(order.user, self.user)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual({item.product_id: item.quantity for item in order.items.all()}, {tea.pk: 2, mug.pk: 3})
        tea.refresh_from_db()
        mug.refresh_from_db()
        self.assertEqual(tea.stock, 8)
        self.assertEqual(mug.stock, 0)

    def test_copies_current_price_onto_each_item(self):
        product = make_product(price="7.25")

        order = place_order(self.user, [(product.pk, 1)], self.address.pk)

        self.assertEqual(order.items.get().unit_price, Decimal("7.25"))

    def test_merges_repeated_lines_for_the_same_product(self):
        product = make_product(stock=10)

        order = place_order(self.user, [(product.pk, 2), (product.pk, 3)], self.address.pk)

        item = order.items.get()
        self.assertEqual(item.quantity, 5)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)

    def test_merged_lines_are_checked_against_stock_together(self):
        product = make_product("Tea", stock=4)

        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [(product.pk, 3), (product.pk, 2)], self.address.pk)

        self.assertEqual(item_errors(caught.exception), ["Only 4 of 'Tea' left in stock."])

    def test_rejects_an_empty_order(self):
        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [], self.address.pk)

        self.assertEqual(item_errors(caught.exception), ["An order needs at least one item."])
        self.assertFalse(Order.objects.exists())

    def test_rejects_unknown_and_inactive_products(self):
        hidden = make_product(is_active=False)
        available = make_product()

        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [(available.pk, 1), (hidden.pk, 1), (99999, 1)], self.address.pk)

        self.assertEqual(
            item_errors(caught.exception),
            [f"Product {hidden.pk} is not available.", "Product 99999 is not available."],
        )

    def test_short_stock_lists_every_short_product_and_changes_nothing(self):
        tea = make_product("Tea", stock=1)
        mug = make_product("Mug", stock=0)
        plenty = make_product("Plenty", stock=50)

        with self.assertRaises(ValidationError) as caught:
            place_order(self.user, [(tea.pk, 2), (mug.pk, 1), (plenty.pk, 1)], self.address.pk)

        self.assertCountEqual(
            item_errors(caught.exception),
            ["Only 1 of 'Tea' left in stock.", "No Mug left in the stock."],
        )
        self.assertFalse(Order.objects.exists())
        self.assertEqual(Product.objects.get(pk=plenty.pk).stock, 50)

    def test_ordering_exactly_the_remaining_stock_succeeds(self):
        product = make_product(stock=2)

        place_order(self.user, [(product.pk, 2)], self.address.pk)

        product.refresh_from_db()
        self.assertEqual(product.stock, 0)


class PlaceOrderAddressTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product(stock=10)
        self.address = make_address(
            self.user,
            label="other",
            custom_label="Mom's house",
            recipient_name="Maria Santos",
            phone="+65 6123 4567",
            line1="1 Orchard Road",
            line2="#05-01",
            city="Singapore",
            region="Central",
            postcode="238824",
            country="SG",
        )

    def assert_rejected_without_side_effects(self, user, address_id):
        with self.assertRaises(ValidationError) as caught:
            place_order(user, [(self.product.pk, 2)], address_id)

        self.assertEqual(address_errors(caught.exception), ["Choose one of your delivery addresses."])
        self.assertFalse(Order.objects.exists())
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock, 10)

    def test_rejects_a_missing_or_unknown_address_and_changes_nothing(self):
        for address_id in (None, 99999):
            with self.subTest(address_id=address_id):
                self.assert_rejected_without_side_effects(self.user, address_id)

    def test_rejects_another_users_address_with_the_same_message(self):
        foreign = make_address(make_user())

        self.assert_rejected_without_side_effects(self.user, foreign.pk)

    def test_staff_cannot_use_another_users_address(self):
        staff = make_user(is_staff=True)

        self.assert_rejected_without_side_effects(staff, self.address.pk)

    def test_copies_the_address_onto_the_order(self):
        order = place_order(self.user, [(self.product.pk, 1)], self.address.pk)

        self.assertEqual(
            Order.objects.get(pk=order.pk).shipping_address,
            {
                "label": "other",
                "custom_label": "Mom's house",
                "label_display": "Mom's house",
                "recipient_name": "Maria Santos",
                "phone": "+65 6123 4567",
                "line1": "1 Orchard Road",
                "line2": "#05-01",
                "city": "Singapore",
                "region": "Central",
                "postcode": "238824",
                "country": "SG",
                "country_display": "Singapore",
            },
        )

    def test_editing_the_address_afterwards_leaves_the_snapshot_unchanged(self):
        order = place_order(self.user, [(self.product.pk, 1)], self.address.pk)
        placed = Order.objects.get(pk=order.pk).shipping_address

        self.address.label = "home"
        self.address.custom_label = ""
        self.address.line1 = "99 New Street"
        self.address.country = "JP"
        self.address.save()

        self.assertEqual(Order.objects.get(pk=order.pk).shipping_address, placed)

    def test_deleting_the_address_afterwards_leaves_the_snapshot_unchanged(self):
        order = place_order(self.user, [(self.product.pk, 1)], self.address.pk)
        placed = Order.objects.get(pk=order.pk).shipping_address

        self.address.delete()

        self.assertEqual(Order.objects.get(pk=order.pk).shipping_address, placed)
        self.assertEqual(placed["label_display"], "Mom's house")
        self.assertEqual(placed["country_display"], "Singapore")


class CancelOrderTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.address = make_address(self.user)

    def test_cancels_pending_order_and_returns_stock(self):
        tea = make_product(stock=10)
        mug = make_product(stock=5)
        order = place_order(self.user, [(tea.pk, 4), (mug.pk, 5)], self.address.pk)

        cancelled = cancel_order(order)

        self.assertEqual(cancelled.status, Order.Status.CANCELLED)
        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.CANCELLED)
        self.assertEqual(Product.objects.get(pk=tea.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=mug.pk).stock, 5)

    def test_reads_the_current_status_not_the_stale_instance(self):
        product = make_product(stock=10)
        order = place_order(self.user, [(product.pk, 1)], self.address.pk)
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
        order = place_order(self.user, [(product.pk, 3)], self.address.pk)
        cancel_order(order)

        with self.assertRaises(ValidationError):
            cancel_order(order)

        self.assertEqual(Product.objects.get(pk=product.pk).stock, 10)
