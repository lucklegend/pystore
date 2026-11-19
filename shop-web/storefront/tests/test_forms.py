from django.test import SimpleTestCase

from config.fixture_secrets import USER_PASSWORD, WRONG_PASSWORD

from storefront.api import ApiError
from storefront.forms import AddToCartForm, LoginForm, ProductForm, RegisterForm, apply_api_errors

CATEGORIES = [{"id": 1, "name": "Tea"}, {"id": 2, "name": "Coffee"}]


def product_data(**overrides) -> dict:
    return {"name": "Kettle", "category": "1", "description": "Boils", "price": "30.5", "stock": "4",
            "image_url": "https://example.com/k.png", "is_active": "on", **overrides}


class RegisterFormTests(SimpleTestCase):
    def data(self, **overrides) -> dict:
        return {"username": "alice", "email": "alice@example.com", "password": USER_PASSWORD,
                "password_confirm": USER_PASSWORD, **overrides}

    def test_valid_when_passwords_match(self):
        self.assertTrue(RegisterForm(self.data()).is_valid())

    def test_mismatched_passwords_error_on_confirm_field(self):
        form = RegisterForm(self.data(password_confirm=WRONG_PASSWORD))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["password_confirm"], ["Passwords don't match."])

    def test_rejects_invalid_email(self):
        form = RegisterForm(self.data(email="not-an-email"))

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)


class ProductFormTests(SimpleTestCase):
    def test_offers_api_categories_plus_none(self):
        form = ProductForm(categories=CATEGORIES)

        choices = form.fields["category"].choices
        self.assertEqual(choices[0][0], "")
        self.assertEqual(choices[1:], [(1, "Tea"), (2, "Coffee")])

    def test_to_payload_matches_the_api_shape(self):
        form = ProductForm(product_data(), categories=CATEGORIES)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.to_payload(),
            {"name": "Kettle", "category": 1, "description": "Boils", "price": "30.5", "stock": 4,
             "image_url": "https://example.com/k.png", "is_active": True},
        )

    def test_blank_category_and_unchecked_visibility(self):
        data = product_data(category="")
        del data["is_active"]
        form = ProductForm(data, categories=CATEGORIES)

        self.assertTrue(form.is_valid(), form.errors)
        payload = form.to_payload()
        self.assertIsNone(payload["category"])
        self.assertFalse(payload["is_active"])

    def test_rejects_bad_values(self):
        cases = {"price": "-1", "stock": "-1", "category": "3", "image_url": "not a url"}
        for field, value in cases.items():
            with self.subTest(field=field):
                form = ProductForm(product_data(**{field: value}), categories=CATEGORIES)

                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_rejects_more_than_two_decimal_places(self):
        form = ProductForm(product_data(price="1.005"), categories=CATEGORIES)

        self.assertFalse(form.is_valid())
        self.assertIn("price", form.errors)


class AddToCartFormTests(SimpleTestCase):
    def test_quantity_bounds(self):
        for quantity, valid in (("1", True), ("99", True), ("0", False), ("100", False), ("x", False)):
            with self.subTest(quantity=quantity):
                self.assertEqual(AddToCartForm({"quantity": quantity}).is_valid(), valid)


class ApplyApiErrorsTests(SimpleTestCase):
    def test_puts_known_fields_on_fields_and_the_rest_on_the_form(self):
        form = LoginForm({"username": "alice", "password": USER_PASSWORD})
        form.is_valid()
        error = ApiError(400, {"username": ["Taken."], "token": ["Odd."], "detail": "Nope."})

        apply_api_errors(form, error)

        self.assertEqual(form.errors["username"], ["Taken."])
        self.assertEqual(form.non_field_errors(), ["Odd.", "Nope."])
