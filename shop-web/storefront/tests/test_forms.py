from django.template.loader import render_to_string
from django.test import SimpleTestCase

from config.fixture_secrets import USER_PASSWORD, WRONG_PASSWORD

from storefront.api import ApiError
from storefront.forms import (
    AddressForm,
    AddToCartForm,
    LoginForm,
    ProductForm,
    RegisterForm,
    address_initial,
    apply_api_errors,
    new_address_initial,
)

COUNTRY_CHOICES = [("PH", "Philippines"), ("SG", "Singapore")]
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


def address_data(**overrides) -> dict:
    return {"label": "home", "custom_label": "", "recipient_name": "Alice Cruz", "phone": "+63 912 345 6789",
            "line1": "12 Rizal Street", "line2": "", "city": "Quezon City", "region": "", "postcode": "1100",
            "country": "PH", **overrides}


def saved(**overrides) -> dict:
    return {"id": 1, "label": "home", "custom_label": "", "is_default": False, "recipient_name": "Alice Cruz",
            "phone": "+63 912 345 6789", "line1": "12 Rizal Street", "line2": "", "city": "Quezon City",
            "region": "", "postcode": "1100", "country": "PH", **overrides}


class AddressFormTests(SimpleTestCase):
    def form(self, **overrides) -> AddressForm:
        return AddressForm(address_data(**overrides), countries=COUNTRY_CHOICES)

    def test_offers_a_blank_option_then_the_given_countries(self):
        form = AddressForm(countries=COUNTRY_CHOICES)

        self.assertEqual(form.fields["country"].choices, [("", "Choose a country")] + COUNTRY_CHOICES)

    def test_valid_with_only_the_required_fields(self):
        self.assertTrue(self.form().is_valid())

    def test_required_fields(self):
        form = AddressForm({}, countries=COUNTRY_CHOICES)

        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {"label", "recipient_name", "phone", "line1", "city", "country"})
        self.assertEqual(form.errors["city"], ["This field is required."])

    def test_other_with_a_blank_name_is_valid(self):
        form = self.form(label="other", custom_label="   ")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["custom_label"], "")

    def test_other_keeps_its_name_stripped(self):
        form = self.form(label="other", custom_label="  Mom's house ")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["custom_label"], "Mom's house")

    def test_home_and_office_drop_a_name(self):
        for label in ("home", "office"):
            with self.subTest(label=label):
                form = self.form(label=label, custom_label="Mom's house")

                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["custom_label"], "")

    def test_a_name_over_50_characters_is_rejected(self):
        form = self.form(label="other", custom_label="x" * 51)

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["custom_label"], ["Keep the name to 50 characters or fewer."])

    def test_country_messages(self):
        blank = self.form(country="")
        unknown = self.form(country="ZZ")

        self.assertFalse(blank.is_valid())
        self.assertFalse(unknown.is_valid())
        self.assertEqual(blank.errors["country"], ["Choose a country."])
        self.assertEqual(unknown.errors["country"], ["Choose a country from the list."])

    def test_phone_message(self):
        form = self.form(phone="call me")

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["phone"], ["Enter a valid phone number, for example +63 912 345 6789."])

    def test_to_payload_matches_the_api_shape(self):
        form = self.form(label="other", custom_label="Mom's house", is_default="on", line2="Unit 4")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.to_payload(),
            {"label": "other", "custom_label": "Mom's house", "is_default": True, "recipient_name": "Alice Cruz",
             "phone": "+63 912 345 6789", "line1": "12 Rizal Street", "line2": "Unit 4", "city": "Quezon City",
             "region": "", "postcode": "1100", "country": "PH"},
        )

    def test_unchecked_default_is_false(self):
        form = self.form()

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.to_payload()["is_default"], False)

    def test_partial_renders_the_label_radios_and_each_field_once(self):
        html = render_to_string(
            "storefront/_address_form_fields.html",
            {"form": AddressForm(initial={"label": "home"}, countries=COUNTRY_CHOICES)},
        )

        self.assertEqual(html.count('name="label"'), 3)
        self.assertEqual(html.count('name="custom_label"'), 1)
        self.assertEqual(html.count('name="country"'), 1)
        self.assertIn("Use as my default address", html)


class AddressInitialTests(SimpleTestCase):
    def test_address_initial_prefills_every_form_field(self):
        address = saved(label="other", custom_label="Mom's house", is_default=True)

        initial = address_initial(address)

        self.assertEqual(set(initial), set(AddressForm.base_fields))
        self.assertEqual(initial["custom_label"], "Mom's house")
        self.assertIs(initial["is_default"], True)

    def test_new_address_uses_the_default_over_the_newest(self):
        newest = saved(id=2, recipient_name="Newest", country="SG")
        default = saved(id=1, is_default=True, recipient_name="Default", country="PH")

        initial = new_address_initial([default, newest], "Alice Cruz")

        self.assertEqual(initial, {"recipient_name": "Default", "country": "PH", "is_default": False})

    def test_new_address_uses_the_newest_over_the_full_name(self):
        newest = saved(id=2, recipient_name="Newest", country="SG")
        older = saved(id=1, recipient_name="Older", country="PH")

        initial = new_address_initial([newest, older], "Alice Cruz")

        self.assertEqual(initial, {"recipient_name": "Newest", "country": "SG", "is_default": False})

    def test_new_address_with_none_saved_uses_the_full_name_and_checks_default(self):
        self.assertEqual(
            new_address_initial([], "Alice Cruz"),
            {"recipient_name": "Alice Cruz", "country": "", "is_default": True},
        )


class ApplyApiErrorsTests(SimpleTestCase):
    def test_puts_known_fields_on_fields_and_the_rest_on_the_form(self):
        form = LoginForm({"username": "alice", "password": USER_PASSWORD})
        form.is_valid()
        error = ApiError(400, {"username": ["Taken."], "token": ["Odd."], "detail": "Nope."})

        apply_api_errors(form, error)

        self.assertEqual(form.errors["username"], ["Taken."])
        self.assertEqual(form.non_field_errors(), ["Odd.", "Nope."])
