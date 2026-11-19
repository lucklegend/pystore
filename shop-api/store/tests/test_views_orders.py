from rest_framework import status
from rest_framework.test import APITestCase

from store.models import Order, Product

from .factories import make_order, make_product, make_user

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


class CreateOrderTests(APITestCase):
    def setUp(self):
        self.user = make_user("alice")
        self.client.force_authenticate(self.user)

    def post(self, items):
        return self.client.post(ORDERS, {"items": items}, format="json")

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

        self.client.post(ORDERS, {"user": other.pk, "items": [{"product": product.pk, "quantity": 1}]}, format="json")

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


class CancelOrderApiTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product(stock=10)

    def place(self, quantity: int = 2) -> int:
        self.client.force_authenticate(self.user)
        response = self.client.post(
            ORDERS, {"items": [{"product": self.product.pk, "quantity": quantity}]}, format="json"
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
