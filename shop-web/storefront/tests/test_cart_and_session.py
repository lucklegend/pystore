from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.test import SimpleTestCase

from storefront.cart import CART_KEY, MAX_QUANTITY, Cart
from storefront.session import current_token, current_user, sign_in, sign_out


class CartTests(SimpleTestCase):
    def setUp(self):
        self.session = SessionStore()
        self.cart = Cart(self.session)

    def test_starts_empty(self):
        self.assertEqual(self.cart.lines, {})
        self.assertEqual(self.cart.count, 0)

    def test_add_accumulates_quantity(self):
        self.cart.add(5)
        self.cart.add(5, 2)
        self.cart.add(7, 4)

        self.assertEqual(self.cart.lines, {5: 3, 7: 4})
        self.assertEqual(self.cart.count, 7)

    def test_quantity_is_capped(self):
        self.cart.add(5, MAX_QUANTITY)
        self.cart.add(5, 10)

        self.assertEqual(self.cart.lines, {5: MAX_QUANTITY})

    def test_set_replaces_quantity_and_zero_or_less_removes(self):
        self.cart.add(5, 3)
        self.cart.set(5, 1)
        self.assertEqual(self.cart.lines, {5: 1})

        self.cart.set(5, 0)
        self.cart.set(6, -2)
        self.assertEqual(self.cart.lines, {})

    def test_remove_and_clear(self):
        self.cart.add(1)
        self.cart.add(2)

        self.cart.remove(1)
        self.assertEqual(self.cart.lines, {2: 1})

        self.cart.clear()
        self.assertEqual(self.cart.lines, {})

    def test_keep_only_drops_other_products(self):
        for product_id in (1, 2, 3):
            self.cart.add(product_id)

        self.cart.keep_only({1, 3, 99})

        self.assertEqual(self.cart.lines, {1: 1, 3: 1})

    def test_stores_string_keys_and_marks_session_modified(self):
        self.session.modified = False

        self.cart.add(5, 2)

        self.assertEqual(self.session[CART_KEY], {"5": 2})
        self.assertTrue(self.session.modified)

    def test_survives_a_session_round_trip(self):
        self.cart.add(5, 2)
        self.session.save()

        reloaded = Cart(SessionStore(session_key=self.session.session_key))

        self.assertEqual(reloaded.lines, {5: 2})


class ShopSessionTests(SimpleTestCase):
    def setUp(self):
        self.session = SessionStore()
        self.session["unrelated"] = "keep me"
        self.session.save()

    def test_sign_in_stores_token_and_user(self):
        sign_in(self.session, "tok", {"username": "alice"})

        self.assertEqual(current_token(self.session), "tok")
        self.assertEqual(current_user(self.session), {"username": "alice"})

    def test_sign_out_removes_only_shop_keys(self):
        sign_in(self.session, "tok", {"username": "alice"})

        sign_out(self.session)

        self.assertIsNone(current_token(self.session))
        self.assertIsNone(current_user(self.session))
        self.assertEqual(self.session["unrelated"], "keep me")

    def test_sign_out_when_not_signed_in_is_harmless(self):
        sign_out(self.session)

        self.assertIsNone(current_user(self.session))
