import json
from unittest.mock import create_autospec

import requests
from django.test import SimpleTestCase

from config.fixture_secrets import USER_PASSWORD
from storefront.api import ApiError, ShopApi, flatten_errors


class FakeResponse:
    def __init__(self, status_code: int = 200, body=None, text: str | None = None):
        self.status_code = status_code
        self.text = text if text is not None else ("" if body is None else json.dumps(body))
        self.content = self.text.encode()

    def json(self):
        return json.loads(self.text)


class FlattenErrorsTests(SimpleTestCase):
    def test_handles_each_payload_shape(self):
        cases = [
            (None, []),
            ("Broken.", ["Broken."]),
            (["One.", "Two."], ["One.", "Two."]),
            ({"name": ["Required."]}, ["name: Required."]),
            ({"detail": "Nope."}, ["Nope."]),
            ({"non_field_errors": ["Bad pair."]}, ["Bad pair."]),
            ({"items": [{"quantity": ["Too many."]}]}, ["quantity: Too many."]),
            (42, ["42"]),
        ]
        for data, expected in cases:
            with self.subTest(data=data):
                self.assertEqual(flatten_errors(data), expected)


class ApiErrorTests(SimpleTestCase):
    def test_message_joins_all_errors(self):
        error = ApiError(400, {"detail": "Nope.", "price": ["Too low."]})

        self.assertEqual(error.message, "Nope. price: Too low.")
        self.assertEqual(str(error), "Nope. price: Too low.")

    def test_message_falls_back_to_status(self):
        self.assertEqual(ApiError(500, None).message, "Request failed (500).")

    def test_splits_field_and_general_errors(self):
        error = ApiError(400, {"email": ["Taken."], "detail": "Nope.", "non_field_errors": ["Bad."]})

        self.assertEqual(error.field_errors(), {"email": ["Taken."]})
        self.assertEqual(error.general_errors(), ["Nope.", "Bad."])

    def test_non_dict_payload_is_all_general(self):
        error = ApiError(400, ["First.", "Second."])

        self.assertEqual(error.field_errors(), {})
        self.assertEqual(error.general_errors(), ["First.", "Second."])


class ShopApiRequestTests(SimpleTestCase):
    def setUp(self):
        self.http = create_autospec(requests.Session, instance=True)
        self.http.request.return_value = FakeResponse(200, {"ok": True})

    def make_api(self, token: str | None = None) -> ShopApi:
        return ShopApi("http://api.test/api/", token=token, http=self.http, timeout=2.5)

    def sent(self):
        return self.http.request.call_args

    def test_builds_url_headers_and_timeout(self):
        result = self.make_api().get_product(7)

        self.assertEqual(result, {"ok": True})
        args, kwargs = self.sent()
        self.assertEqual(args, ("GET", "http://api.test/api/products/7/"))
        self.assertEqual(kwargs["headers"], {"Accept": "application/json"})
        self.assertEqual(kwargs["timeout"], 2.5)

    def test_sends_token_when_logged_in(self):
        self.make_api(token="abc").list_categories()

        self.assertEqual(self.sent().kwargs["headers"]["Authorization"], "Token abc")

    def test_raises_api_error_with_payload_on_4xx_and_5xx(self):
        for status in (400, 404, 500):
            with self.subTest(status=status):
                self.http.request.return_value = FakeResponse(status, {"detail": "Nope."})

                with self.assertRaises(ApiError) as caught:
                    self.make_api().list_categories()

                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.data, {"detail": "Nope."})

    def test_non_json_error_body_becomes_detail(self):
        self.http.request.return_value = FakeResponse(502, text="<html>" + "x" * 300)

        with self.assertRaises(ApiError) as caught:
            self.make_api().list_categories()

        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(len(caught.exception.data["detail"]), 200)

    def test_empty_body_returns_none(self):
        self.http.request.return_value = FakeResponse(204)

        self.assertIsNone(self.make_api().delete_product(3))

    def test_network_failure_becomes_503(self):
        self.http.request.side_effect = requests.ConnectionError("refused")

        with self.assertRaises(ApiError) as caught:
            self.make_api().list_categories()

        self.assertEqual(caught.exception.status, 503)
        self.assertIn("unavailable", caught.exception.message)


class ShopApiEndpointTests(SimpleTestCase):
    def setUp(self):
        self.http = create_autospec(requests.Session, instance=True)
        self.http.request.return_value = FakeResponse(200, {})
        self.api = ShopApi("http://api.test/api", http=self.http)

    def test_each_method_calls_the_right_endpoint(self):
        cases = [
            (
                lambda: self.api.login("u", USER_PASSWORD),
                "POST",
                "auth/login/",
                None,
                {"username": "u", "password": USER_PASSWORD},
            ),
            (
                lambda: self.api.register("u", "e@x.com", USER_PASSWORD),
                "POST",
                "auth/register/",
                None,
                {"username": "u", "email": "e@x.com", "password": USER_PASSWORD},
            ),
            (self.api.logout, "POST", "auth/logout/", None, None),
            (self.api.me, "GET", "auth/me/", None, None),
            (lambda: self.api.create_handoff("st"), "POST", "auth/handoff/", None, {"state": "st"}),
            (
                lambda: self.api.redeem_handoff("cd", "st", "secret"),
                "POST",
                "auth/handoff/redeem/",
                None,
                {"code": "cd", "state": "st"},
            ),
            (lambda: self.api.get_cms_page("/about/"), "GET", "cms/pages/resolve/", {"path": "/about/"}, None),
            (self.api.get_cms_navigation, "GET", "cms/navigation/", None, None),
            (self.api.list_categories, "GET", "categories/", None, None),
            (lambda: self.api.list_products({"search": "tea"}), "GET", "products/", {"search": "tea"}, None),
            (lambda: self.api.get_product(4), "GET", "products/4/", None, None),
            (lambda: self.api.create_product({"name": "N"}), "POST", "products/", None, {"name": "N"}),
            (lambda: self.api.update_product(4, {"name": "N"}), "PUT", "products/4/", None, {"name": "N"}),
            (lambda: self.api.delete_product(4), "DELETE", "products/4/", None, None),
            (lambda: self.api.list_orders(3), "GET", "orders/", {"page": 3}, None),
            (lambda: self.api.get_order(9), "GET", "orders/9/", None, None),
            (lambda: self.api.cancel_order(9), "POST", "orders/9/cancel/", None, None),
        ]
        for call, method, path, params, body in cases:
            with self.subTest(path=path, method=method):
                call()

                args, kwargs = self.http.request.call_args
                self.assertEqual(args, (method, f"http://api.test/api/{path}"))
                self.assertEqual(kwargs["params"], params)
                self.assertEqual(kwargs["json"], body)

    def test_redeem_handoff_sends_the_client_secret_header(self):
        self.api.redeem_handoff("cd", "st", "s3cret")

        self.assertEqual(
            self.http.request.call_args.kwargs["headers"],
            {"Accept": "application/json", "X-SSO-Client-Secret": "s3cret"},
        )

    def test_redeem_handoff_keeps_the_token_out_when_none_is_set(self):
        self.api.redeem_handoff("cd", "st", "s3cret")

        self.assertNotIn("Authorization", self.http.request.call_args.kwargs["headers"])

    def test_extra_headers_merge_with_the_token(self):
        api = ShopApi("http://api.test/api", token="abc", http=self.http)

        api.redeem_handoff("cd", "st", "s3cret")

        self.assertEqual(
            self.http.request.call_args.kwargs["headers"],
            {"Accept": "application/json", "X-SSO-Client-Secret": "s3cret", "Authorization": "Token abc"},
        )

    def test_other_methods_send_no_secret_header(self):
        self.api.get_cms_navigation()

        self.assertNotIn("X-SSO-Client-Secret", self.http.request.call_args.kwargs["headers"])

    def test_create_order_sends_cart_lines_as_items(self):
        self.api.create_order({3: 2, 8: 1})

        self.assertEqual(
            self.http.request.call_args.kwargs["json"],
            {"items": [{"product": 3, "quantity": 2}, {"product": 8, "quantity": 1}]},
        )
