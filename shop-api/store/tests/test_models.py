from decimal import Decimal

from django.test import TestCase

from store.models import Order

from .factories import make_category, make_order, make_product, make_user


class OrderTotalTests(TestCase):
    def test_total_sums_item_subtotals(self):
        user = make_user()
        order = make_order(user, [(make_product(price="2.50"), 3), (make_product(price="10.00"), 1)])

        self.assertEqual(order.total, Decimal("17.50"))

    def test_total_of_empty_order_is_zero(self):
        order = Order.objects.create(user=make_user())

        self.assertEqual(order.total, Decimal("0.00"))

    def test_total_uses_price_copied_at_checkout(self):
        product = make_product(price="5.00")
        order = make_order(make_user(), [(product, 2)])

        product.price = Decimal("99.00")
        product.save()

        self.assertEqual(order.total, Decimal("10.00"))


class OrderItemTests(TestCase):
    def test_subtotal_is_unit_price_times_quantity(self):
        order = make_order(make_user(), [(make_product(price="3.20"), 4)])

        self.assertEqual(order.items.get().subtotal, Decimal("12.80"))


class StrTests(TestCase):
    def test_category_and_product_use_their_name(self):
        self.assertEqual(str(make_category("Tea")), "Tea")
        self.assertEqual(str(make_product("Green tea")), "Green tea")

    def test_order_shows_id_and_status_label(self):
        order = Order.objects.create(user=make_user(), status=Order.Status.SHIPPED)

        self.assertEqual(str(order), f"Order #{order.pk} (Shipped)")


class CategoryDeletionTests(TestCase):
    def test_deleting_a_category_keeps_its_products(self):
        category = make_category()
        product = make_product(category=category)

        category.delete()
        product.refresh_from_db()

        self.assertIsNone(product.category)
