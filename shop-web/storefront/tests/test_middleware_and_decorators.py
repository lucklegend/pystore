from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from storefront.api import ApiError
from storefront.decorators import shop_login_required, shop_staff_required
from storefront.session import TOKEN_KEY, USER_KEY

from .helpers import CUSTOMER, STAFF, StorefrontTestCase, page, product


@override_settings(SHOP_API_URL="http://api.test/api", SHOP_API_TIMEOUT=1.5)
class ShopApiMiddlewareTests(StorefrontTestCase):
    def test_builds_client_with_session_token(self):
        self.log_in(token="tok-123")

        self.client.get("/shop/cart/")

        self.api_class.assert_called_with("http://api.test/api", token="tok-123", timeout=1.5)

    def test_anonymous_requests_get_no_token(self):
        self.client.get("/shop/cart/")

        self.api_class.assert_called_with("http://api.test/api", token=None, timeout=1.5)

    def test_401_signs_out_and_redirects_to_login(self):
        self.log_in()
        self.api.get_order.side_effect = ApiError(401, {"detail": "Invalid token."})

        response = self.client.get("/shop/orders/5/")

        self.assertRedirects(response, "/account/login/?next=%2Fshop%2Forders%2F5%2F", fetch_redirect_response=False)
        self.assertNotIn(TOKEN_KEY, self.client.session)
        self.assertNotIn(USER_KEY, self.client.session)
        self.assertIn("Your session has expired. Please log in again.", self.messages(response))

    def test_404_becomes_not_found_page(self):
        self.api.get_product.side_effect = ApiError(404, {"detail": "Not found."})

        response = self.client.get("/shop/products/9/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Page not found", status_code=404)

    def test_other_errors_render_the_api_error_page(self):
        cases = [(403, 403, "Not allowed"), (503, 503, "Shop temporarily unavailable"), (500, 502, "Something went wrong"),
                 (400, 502, "Something went wrong")]
        for api_status, page_status, heading in cases:
            with self.subTest(api_status=api_status):
                self.api.get_product.side_effect = ApiError(api_status, {"detail": "Upstream said no."})

                response = self.client.get("/shop/products/1/")

                self.assertEqual(response.status_code, page_status)
                self.assertTemplateUsed(response, "storefront/api_error.html")
                self.assertContains(response, heading, status_code=page_status)
                self.assertContains(response, "Upstream said no.", status_code=page_status)

    def test_non_api_exceptions_are_left_alone(self):
        self.api.get_product.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.client.get("/shop/products/1/")


class DecoratorTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def call(self, decorated, shop_user):
        request = self.factory.get("/shop/orders/?page=2")
        request.shop_user = shop_user
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return decorated(request)

    @staticmethod
    def view(request):
        return HttpResponse("ok")

    def test_login_required_redirects_anonymous_users_with_next(self):
        response = self.call(shop_login_required(self.view), None)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/account/login/?next=%2Fshop%2Forders%2F%3Fpage%3D2")

    def test_login_required_lets_users_through(self):
        response = self.call(shop_login_required(self.view), CUSTOMER)

        self.assertEqual(response.content, b"ok")

    def test_staff_required(self):
        decorated = shop_staff_required(self.view)

        self.assertEqual(self.call(decorated, None).status_code, 302)
        self.assertEqual(self.call(decorated, STAFF).content, b"ok")
        with self.assertRaises(PermissionDenied):
            self.call(decorated, CUSTOMER)

    def test_customers_get_the_403_page_from_staff_views(self):
        self.log_in(CUSTOMER)

        response = self.client.get("/shop/manage/products/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Not allowed", status_code=403)
        self.api.list_products.assert_not_called()


class ContextProcessorTests(StorefrontTestCase):
    def test_exposes_user_and_cart_count(self):
        self.log_in(CUSTOMER)
        self.fill_cart({1: 2, 2: 3})
        self.api.list_products.return_value = page([product(1), product(2)])

        response = self.client.get("/shop/cart/")

        self.assertEqual(response.context["shop_user"], CUSTOMER)
        self.assertEqual(response.context["cart_count"], 5)
        self.assertContains(response, "Hi, alice")
