from rest_framework import status
from rest_framework.test import APITestCase

from store.models import DeliveryAddress, Order, Product

from .factories import make_address, make_order, make_product, make_user

ORDERS = "/api/orders/"


def order_url(order_id: int) -> str:
    return f"{ORDERS}{order_id}/"


def cancel_url(order_id: int) -> str:
    return f"{ORDERS}{order_id}/cancel/"


class OrderAccessTests(APITestCase):
    def test_requires_authentication(self):
        responses = [self.client.get(ORDERS), self.client.post(ORDERS, {}, format="json")]

        self.assertEqual([response.status_code for response in responses], [status.HTTP_401_UNAUTHORIZED] * 2)

    def test_customers_see_only_their_own_orders(self):
        alice, bob = make_user("alice"), make_user("bob")
        product = make_product()
        own = make_order(alice, [(product, 1)])
        others = make_order(bob, [(product, 1)])
        self.client.force_authenticate(alice)

        listing = self.client.get(ORDERS)
        foreign = self.client.get(order_url(others.pk))

        self.assertEqual([order["id"] for order in listing.data["results"]], [own.pk])
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_see_every_order(self):
        product = make_product()
        make_order(make_user(), [(product, 1)])
        make_order(make_user(), [(product, 1)])
        self.client.force_authenticate(make_user(is_staff=True))

        response = self.client.get(ORDERS)

        self.assertEqual(response.data["count"], 2)

    def test_orders_cannot_be_edited_or_deleted(self):
        user = make_user()
        order = make_order(user, [(make_product(), 1)])
        self.client.force_authenticate(user)

        responses = [
            self.client.patch(order_url(order.pk), {"status": "paid"}, format="json"),
            self.client.delete(order_url(order.pk)),
        ]

        self.assertEqual(
            [response.status_code for response in responses], [status.HTTP_405_METHOD_NOT_ALLOWED] * 2
        )


class OrderDetailTests(APITestCase):
    def test_serializes_items_and_total(self):
        user = make_user("alice")
        order = make_order(user, [(make_product("Tea", price="2.50"), 2)])
        self.client.force_authenticate(user)

        response = self.client.get(order_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "alice")
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["total"], "5.00")
        [item] = response.data["items"]
        self.assertEqual(item["product_name"], "Tea")
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(item["unit_price"], "2.50")
        self.assertEqual(item["subtotal"], "5.00")

    def test_serializes_the_frozen_shipping_address(self):
        user = make_user()
        address = make_address(user, label=DeliveryAddress.Label.OTHER, custom_label="Mom's house", country="SG")
        order = Order.objects.create(user=user, **address.snapshot_fields())
        address.delete()
        self.client.force_authenticate(user)

        response = self.client.get(order_url(order.pk))

        shipping = response.data["shipping_address"]
        self.assertEqual(shipping["label"], "other")
        self.assertEqual(shipping["custom_label"], "Mom's house")
        self.assertEqual(shipping["label_display"], "Mom's house")
        self.assertEqual(shipping["country"], "SG")
        self.assertEqual(shipping["country_display"], "Singapore")

    def test_an_order_from_before_addresses_has_a_null_shipping_address(self):
        user = make_user()
        order = make_order(user, [(make_product(), 1)])
        self.client.force_authenticate(user)

        response = self.client.get(order_url(order.pk))

        self.assertIn("shipping_address", response.data)
        self.assertIsNone(response.data["shipping_address"])


class CreateOrderTests(APITestCase):
    def setUp(self):
        self.user = make_user("alice")
        self.address = make_address(self.user)
        self.client.force_authenticate(self.user)

    def post(self, items):
        return self.client.post(ORDERS, {"items": items, "delivery_address": self.address.pk}, format="json")

    def test_places_an_order_for_the_current_user(self):
        product = make_product(price="3.00", stock=5)

        response = self.post([{"product": product.pk, "quantity": 2}])

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["username"], "alice")
        self.assertEqual(response.data["total"], "6.00")
        self.assertEqual(Order.objects.get().user, self.user)
        self.assertEqual(Product.objects.get(pk=product.pk).stock, 3)

    def test_ignores_a_user_field_in_the_payload(self):
        other = make_user("mallory")
        product = make_product()

        self.client.post(
            ORDERS,
            {"user": other.pk, "items": [{"product": product.pk, "quantity": 1}], "delivery_address": self.address.pk},
            format="json",
        )

        self.assertEqual(Order.objects.get().user, self.user)

    def test_rejects_invalid_payloads(self):
        product = make_product()
        cases = {
            "no items": [],
            "zero quantity": [{"product": product.pk, "quantity": 0}],
            "quantity over 99": [{"product": product.pk, "quantity": 100}],
            "missing product": [{"quantity": 1}],
        }
        for label, items in cases.items():
            with self.subTest(label):
                response = self.post(items)

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("items", response.data)
        self.assertFalse(Order.objects.exists())

    def test_reports_short_stock_as_400(self):
        product = make_product("Tea", stock=1)

        response = self.post([{"product": product.pk, "quantity": 2}])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["items"], ["Only 1 of 'Tea' left in stock."])

    def test_ships_to_the_chosen_address(self):
        product = make_product()

        response = self.post([{"product": product.pk, "quantity": 1}])

        self.assertEqual(response.data["shipping_address"]["line1"], self.address.line1)
        self.assertEqual(response.data["shipping_address"]["country_display"], "Philippines")


class CreateOrderAddressTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product(stock=5)
        self.client.force_authenticate(self.user)

    def post(self, payload: dict):
        items = [{"product": self.product.pk, "quantity": 1}]
        return self.client.post(ORDERS, {"items": items, **payload}, format="json")

    def assert_nothing_placed(self):
        self.assertFalse(Order.objects.exists())
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock, 5)

    def test_missing_unknown_and_foreign_ids_get_one_identical_body(self):
        foreign = make_address(make_user())
        cases = {
            "missing": {},
            "unknown": {"delivery_address": foreign.pk + 1000},
            "foreign": {"delivery_address": foreign.pk},
            "oversized": {"delivery_address": 2**70},
        }
        for label, payload in cases.items():
            with self.subTest(label):
                response = self.post(payload)

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.json(), {"delivery_address": ["Choose one of your delivery addresses."]})
        self.assert_nothing_placed()

    def test_staff_cannot_ship_to_another_users_address(self):
        foreign = make_address(make_user())
        self.client.force_authenticate(make_user(is_staff=True))

        response = self.post({"delivery_address": foreign.pk})

        self.assertEqual(response.json(), {"delivery_address": ["Choose one of your delivery addresses."]})
        self.assert_nothing_placed()

    def test_rejects_an_id_that_is_not_a_positive_integer(self):
        for value in ("abc", [1, 2], 0, -1, None):
            with self.subTest(value=value):
                response = self.post({"delivery_address": value})

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("delivery_address", response.data)
        self.assert_nothing_placed()


class CancelOrderApiTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.address = make_address(self.user)
        self.product = make_product(stock=10)

    def place(self, quantity: int = 2) -> int:
        self.client.force_authenticate(self.user)
        response = self.client.post(
            ORDERS,
            {"items": [{"product": self.product.pk, "quantity": quantity}], "delivery_address": self.address.pk},
            format="json",
        )
        return response.data["id"]

    def test_owner_can_cancel_a_pending_order(self):
        order_id = self.place(3)

        response = self.client.post(cancel_url(order_id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock, 10)

    def test_cancelling_a_non_pending_order_is_400(self):
        order_id = self.place()
        self.client.post(cancel_url(order_id))

        response = self.client.post(cancel_url(order_id))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Only pending orders can be cancelled.")

    def test_other_customers_cannot_cancel(self):
        order_id = self.place()
        self.client.force_authenticate(make_user())

        response = self.client.post(cancel_url(order_id))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.PENDING)

    def test_staff_can_cancel_any_order(self):
        order_id = self.place()
        self.client.force_authenticate(make_user(is_staff=True))

        response = self.client.post(cancel_url(order_id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
