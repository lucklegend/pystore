from decimal import Decimal

from storefront.api import ApiError

from .helpers import CUSTOMER, STAFF, StorefrontTestCase, address, order, page, product

NEW_ADDRESS = {
    "label": "office",
    "custom_label": "",
    "recipient_name": "Alice Cruz",
    "phone": "+63 912 345 6789",
    "line1": "8 Ayala Avenue",
    "city": "Makati",
    "country": "PH",
}


class ProductListTests(StorefrontTestCase):
    def test_passes_search_category_and_page_to_the_api(self):
        self.client.get("/shop/", {"q": "  tea ", "category": "3", "page": "2"})

        self.api.list_products.assert_called_once_with({"page": 2, "search": "tea", "category": "3"})

    def test_drops_invalid_filters(self):
        for page_param in ("0", "-1", "abc"):
            with self.subTest(page=page_param):
                self.api.list_products.reset_mock()

                self.client.get("/shop/", {"category": "all", "page": page_param})

                self.api.list_products.assert_called_once_with({"page": 1})

    def test_renders_products_and_pager_links(self):
        self.api.list_products.return_value = page(
            [product(1, name="Sencha")], next_url="http://api/?page=3", previous_url="http://api/?page=1"
        )
        self.api.list_categories.return_value = [{"id": 3, "name": "Tea"}]

        response = self.client.get("/shop/", {"q": "tea", "page": "2"})

        self.assertContains(response, "Sencha")
        self.assertEqual(response.context["prev_query"], "q=tea&page=1")
        self.assertEqual(response.context["next_query"], "q=tea&page=3")

    def test_no_pager_links_on_a_single_page(self):
        response = self.client.get("/shop/")

        self.assertIsNone(response.context["prev_query"])
        self.assertIsNone(response.context["next_query"])


class ProductDetailTests(StorefrontTestCase):
    def test_renders_the_product(self):
        self.api.get_product.return_value = product(4, name="Kettle", stock=3)

        response = self.client.get("/shop/products/4/")

        self.api.get_product.assert_called_once_with(4)
        self.assertContains(response, "Kettle")
        self.assertContains(response, "3 in stock")
        self.assertNotContains(response, "Edit this product")

    def test_out_of_stock_hides_add_to_cart(self):
        self.api.get_product.return_value = product(4, stock=0)

        response = self.client.get("/shop/products/4/")

        self.assertContains(response, "Out of stock")
        self.assertNotContains(response, "Add to cart")

    def test_staff_get_an_edit_link(self):
        self.log_in(STAFF)
        self.api.get_product.return_value = product(4)

        self.assertContains(self.client.get("/shop/products/4/"), "Edit this product")


class CartTests(StorefrontTestCase):
    def test_add_checks_the_product_and_stores_quantity(self):
        self.api.get_product.return_value = product(4, name="Kettle")
        self.fill_cart({4: 1})

        response = self.client.post("/shop/cart/add/4/", {"quantity": "2"})

        self.assertRedirects(response, "/shop/cart/", fetch_redirect_response=False)
        self.assertEqual(self.cart(), {4: 3})
        self.assertIn("Added Kettle to your cart.", self.messages(response))

    def test_add_rejects_bad_quantity_without_calling_the_api(self):
        response = self.client.post("/shop/cart/add/4/", {"quantity": "0"})

        self.api.get_product.assert_not_called()
        self.assertEqual(self.cart(), {})
        self.assertIn("Choose a quantity between 1 and 99.", self.messages(response))

    def test_add_for_a_missing_product_is_404_and_leaves_the_cart(self):
        self.api.get_product.side_effect = ApiError(404, {"detail": "Not found."})

        response = self.client.post("/shop/cart/add/4/", {"quantity": "1"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.cart(), {})

    def test_cart_actions_require_post(self):
        for url in (
            "/shop/cart/add/4/",
            "/shop/cart/update/4/",
            "/shop/cart/remove/4/",
            "/shop/cart/address/",
            "/shop/checkout/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_empty_cart_does_not_call_the_api(self):
        response = self.client.get("/shop/cart/")

        self.api.list_products.assert_not_called()
        self.assertContains(response, "Your cart is empty.")

    def test_cart_fetches_fresh_prices_and_totals(self):
        self.fill_cart({1: 2, 2: 1})
        self.api.list_products.return_value = page([product(1, price="2.50"), product(2, price="10.00")])

        response = self.client.get("/shop/cart/")

        self.api.list_products.assert_called_once_with({"ids": "1,2", "page_size": 100})
        self.assertEqual([item["subtotal"] for item in response.context["items"]], [Decimal("5.00"), Decimal("10.00")])
        self.assertEqual(response.context["total"], Decimal("15.00"))

    def test_unavailable_products_are_removed_with_a_warning(self):
        self.fill_cart({1: 2, 2: 1})
        self.api.list_products.return_value = page([product(1)])

        response = self.client.get("/shop/cart/")

        self.assertEqual(self.cart(), {1: 2})
        self.assertEqual(len(response.context["items"]), 1)
        self.assertContains(response, "no longer available")

    def test_update_sets_quantity_and_zero_removes(self):
        self.fill_cart({1: 2, 2: 1})

        self.client.post("/shop/cart/update/1/", {"quantity": "5"})
        self.client.post("/shop/cart/update/2/", {"quantity": "0"})

        self.assertEqual(self.cart(), {1: 5})

    def test_update_rejects_non_numbers(self):
        self.fill_cart({1: 2})

        for raw in ("", "-1", "two", "1.5"):
            with self.subTest(raw=raw):
                response = self.client.post("/shop/cart/update/1/", {"quantity": raw})

                self.assertEqual(self.cart(), {1: 2})
                self.assertIn("Quantity must be a whole number.", self.messages(response))

    def test_remove(self):
        self.fill_cart({1: 2, 2: 1})

        self.client.post("/shop/cart/remove/1/")

        self.assertEqual(self.cart(), {2: 1})


class CheckoutTests(StorefrontTestCase):
    def test_anonymous_users_log_in_and_return_to_the_cart(self):
        self.fill_cart({1: 1})

        response = self.client.post("/shop/checkout/")

        self.assertRedirects(response, "/account/login/?next=%2Fshop%2Fcart%2F", fetch_redirect_response=False)
        self.assertEqual(self.cart(), {1: 1})
        self.api.create_order.assert_not_called()

    def test_empty_cart(self):
        self.log_in()

        response = self.client.post("/shop/checkout/")

        self.assertRedirects(response, "/shop/cart/", fetch_redirect_response=False)
        self.api.create_order.assert_not_called()

    def test_places_the_order_and_clears_the_cart(self):
        self.log_in()
        self.fill_cart({1: 2, 3: 1})
        self.api.create_order.return_value = order(42)

        response = self.client.post("/shop/checkout/", {"delivery_address": "5"})

        self.api.create_order.assert_called_once_with({1: 2, 3: 1}, 5)
        self.assertRedirects(response, "/shop/orders/42/", fetch_redirect_response=False)
        self.assertEqual(self.cart(), {})
        self.assertIn("Thanks! Order #42 has been placed.", self.messages(response))

    def test_success_forgets_the_picked_address(self):
        self.log_in()
        self.fill_cart({1: 1})
        session = self.client.session
        session["delivery_address"] = 5
        self.save_session(session)
        self.api.create_order.return_value = order(42)

        self.client.post("/shop/checkout/", {"delivery_address": "5"})

        self.assertNotIn("delivery_address", self.client.session)

    def test_stock_problems_keep_the_cart_and_the_picked_address(self):
        self.log_in()
        self.fill_cart({1: 5})
        self.api.create_order.side_effect = ApiError(400, {"items": ["Only 1 of 'Tea' left in stock."]})

        response = self.client.post("/shop/checkout/", {"delivery_address": "5"})

        self.assertRedirects(response, "/shop/cart/", fetch_redirect_response=False)
        self.assertEqual(self.cart(), {1: 5})
        self.assertEqual(self.client.session["delivery_address"], 5)
        self.assertIn("Only 1 of 'Tea' left in stock.", self.messages(response))

    def test_an_address_the_api_refuses_keeps_the_cart(self):
        self.log_in()
        self.fill_cart({1: 1})
        self.api.create_order.side_effect = ApiError(
            400, {"delivery_address": ["Choose one of your delivery addresses."]}
        )

        response = self.client.post("/shop/checkout/", {"delivery_address": "99"})

        self.assertRedirects(response, "/shop/cart/", fetch_redirect_response=False)
        self.assertEqual(self.cart(), {1: 1})
        self.assertIn("Choose one of your delivery addresses.", self.messages(response))

    def test_no_address_picked_makes_no_api_call(self):
        self.log_in()
        self.fill_cart({1: 1})

        for data in ({}, {"delivery_address": ""}, {"delivery_address": "home"}, {"delivery_address": "-1"}):
            with self.subTest(data=data):
                response = self.client.post("/shop/checkout/", data)

                self.assertRedirects(response, "/shop/cart/", fetch_redirect_response=False)
                self.assertIn("Choose a delivery address.", self.messages(response))
        self.api.create_order.assert_not_called()
        self.assertEqual(self.cart(), {1: 1})


class CartAddressTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.api.list_products.return_value = page([product(1, name="Sencha")])

    def pick_address(self, address_id: int | None) -> None:
        session = self.client.session
        session["delivery_address"] = address_id
        self.save_session(session)

    def test_anonymous_cart_makes_no_address_calls(self):
        self.fill_cart({1: 1})

        response = self.client.get("/shop/cart/")

        self.api.list_addresses.assert_not_called()
        self.api.list_countries.assert_not_called()
        self.assertContains(response, "Log in to check out")
        self.assertContains(response, "You'll choose a delivery address after you log in.")
        self.assertNotContains(response, "Deliver to")

    def test_empty_cart_makes_no_address_calls(self):
        self.log_in()

        response = self.client.get("/shop/cart/")

        self.api.list_addresses.assert_not_called()
        self.api.list_countries.assert_not_called()
        self.assertNotContains(response, "Deliver to")

    def test_preselection(self):
        home = address(1, is_default=True)
        office = address(2, label="office", label_display="Office")
        cases = (
            ("this visit's pick beats the default", [home, office], 2, 2),
            ("the default beats the newest", [home, office], None, 1),
            ("a pick no longer listed falls back to the default", [home, office], 99, 1),
            ("with no default the newest wins", [address(3), address(2)], None, 3),
        )
        self.log_in()
        self.fill_cart({1: 1})
        for name, addresses, picked, expected in cases:
            with self.subTest(name):
                self.api.list_addresses.return_value = addresses
                self.pick_address(picked)

                response = self.client.get("/shop/cart/")

                self.assertEqual(response.context["selected_address_id"], expected)
                self.assertContains(response, f'name="delivery_address" value="{expected}" required checked>')

    def test_lists_addresses_with_the_default_badge(self):
        self.log_in()
        self.fill_cart({1: 1})
        self.api.list_addresses.return_value = [
            address(1, is_default=True),
            address(2, label="other", custom_label="Mom's house", label_display="Mom's house", country_display="Singapore"),
        ]

        response = self.client.get("/shop/cart/")

        self.assertContains(response, "Deliver to")
        self.assertContains(response, '<span class="badge">Default</span>', count=1)
        self.assertContains(response, "Mom&#x27;s house")
        self.assertContains(response, "Singapore")
        self.assertContains(response, "Manage addresses")
        self.assertContains(response, '<details class="add-address">')
        self.assertContains(response, '<button class="button" type="submit" form="checkout-form">Place order</button>')

    def test_no_addresses_disables_place_order_and_opens_the_add_form(self):
        self.log_in({**CUSTOMER, "full_name": "Alice Cruz"})
        self.fill_cart({1: 1})

        response = self.client.get("/shop/cart/")

        self.assertContains(response, '<p id="no-address-hint" class="muted">Add a delivery address to place your order.</p>')
        self.assertContains(response, 'form="checkout-form" disabled aria-describedby="no-address-hint"')
        self.assertContains(response, '<details class="add-address" open>')
        self.assertNotContains(response, "Manage addresses")
        form = response.context["address_form"]
        self.assertEqual(form.initial, {"recipient_name": "Alice Cruz", "country": "", "is_default": True})

    def test_at_the_cap_the_add_block_is_replaced(self):
        self.log_in()
        self.fill_cart({1: 1})
        self.api.list_addresses.return_value = [address(pk) for pk in range(1, 21)]

        response = self.client.get("/shop/cart/")

        self.assertNotContains(response, "Add a new address")
        self.assertContains(
            response,
            "You've saved 20 addresses, the most allowed. Delete one in Manage addresses to add another.",
        )

    def test_inline_add_saves_picks_and_flashes(self):
        cases = (
            (False, "Added Office address and selected it for this order."),
            (True, "Added Office address and selected it for this order. It's now your default."),
        )
        self.log_in()
        self.fill_cart({1: 1})
        for is_default, flash in cases:
            with self.subTest(is_default=is_default):
                self.api.create_address.reset_mock()
                self.api.create_address.return_value = address(
                    7, label="office", label_display="Office", is_default=is_default
                )

                response = self.client.post("/shop/cart/address/", NEW_ADDRESS)

                self.api.create_address.assert_called_once_with(
                    {
                        "label": "office",
                        "custom_label": "",
                        "is_default": False,
                        "recipient_name": "Alice Cruz",
                        "phone": "+63 912 345 6789",
                        "line1": "8 Ayala Avenue",
                        "line2": "",
                        "city": "Makati",
                        "region": "",
                        "postcode": "",
                        "country": "PH",
                    }
                )
                self.assertRedirects(response, "/shop/cart/", fetch_redirect_response=False)
                self.assertEqual(self.client.session["delivery_address"], 7)
                self.assertIn(flash, self.messages(response))

    def test_invalid_inline_add_shows_the_cart_again_with_errors(self):
        self.log_in()
        self.fill_cart({1: 1})
        self.api.list_addresses.return_value = [address(1, is_default=True)]

        response = self.client.post("/shop/cart/address/", {**NEW_ADDRESS, "phone": "call me"})

        self.api.create_address.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sencha")
        self.assertContains(response, "We couldn&#x27;t save that address. Check the details below.")
        self.assertContains(response, "Enter a valid phone number, for example +63 912 345 6789.")
        self.assertContains(response, '<details class="add-address" open>')
        self.assertEqual(response.context["address_form"]["phone"].value(), "call me")
        self.assertIn("autofocus", str(response.context["address_form"]["phone"]))
        self.assertEqual(self.cart(), {1: 1})

    def test_inline_add_refused_by_the_api_shows_the_cart_again_with_errors(self):
        self.log_in()
        self.fill_cart({1: 1})
        self.api.create_address.side_effect = ApiError(400, {"detail": "You can save up to 20 addresses."})

        response = self.client.post("/shop/cart/address/", NEW_ADDRESS)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sencha")
        self.assertContains(response, '<li class="message error">You can save up to 20 addresses.</li>')
        self.assertContains(response, "We couldn&#x27;t save that address. Check the details below.")
        self.assertNotIn("delivery_address", self.client.session)

    def test_logged_out_inline_add_logs_in_and_returns_to_the_cart(self):
        self.fill_cart({1: 1})

        response = self.client.post("/shop/cart/address/", NEW_ADDRESS)

        self.assertRedirects(response, "/account/login/?next=%2Fshop%2Fcart%2F", fetch_redirect_response=False)
        self.api.create_address.assert_not_called()
        self.api.list_countries.assert_not_called()


class OrderViewTests(StorefrontTestCase):
    def test_order_pages_require_login(self):
        for url in ("/shop/orders/", "/shop/orders/1/"):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/account/login/?next="))
        self.api.list_orders.assert_not_called()
        self.api.get_order.assert_not_called()

    def test_order_list(self):
        self.log_in()
        self.api.list_orders.return_value = page([order(7)], next_url="http://api/?page=3")

        response = self.client.get("/shop/orders/", {"page": "2"})

        self.api.list_orders.assert_called_once_with(2)
        self.assertContains(response, "#7")
        self.assertEqual(response.context["next_query"], "page=3")

    def test_order_detail_offers_cancel_only_while_pending(self):
        self.log_in()
        for status, can_cancel in (("pending", True), ("shipped", False)):
            with self.subTest(status=status):
                self.api.get_order.return_value = order(7, status=status)

                response = self.client.get("/shop/orders/7/")

                self.assertEqual("Cancel order" in response.content.decode(), can_cancel)

    def test_order_detail_shows_the_frozen_address_without_a_default_badge(self):
        self.log_in()
        saved = address(
            label="other",
            custom_label="Mom's house",
            label_display="Mom's house",
            country="SG",
            country_display="Singapore",
        )
        # The snapshot has a saved address's keys minus id, is_default and the timestamps.
        shipping = {
            key: value for key, value in saved.items() if key not in ("id", "is_default", "created_at", "updated_at")
        }
        self.api.get_order.return_value = order(7, shipping_address=shipping)

        response = self.client.get("/shop/orders/7/")

        self.assertContains(response, "Shipping to")
        self.assertContains(response, '<span class="eyebrow">Mom&#x27;s house</span>')
        self.assertContains(response, "Singapore")
        self.assertContains(response, "12 Rizal Street")
        self.assertNotContains(response, '<span class="badge">Default</span>')
        self.assertNotContains(response, "No delivery address recorded.")

    def test_a_legacy_order_has_no_address(self):
        self.log_in()
        self.api.get_order.return_value = order(7)

        response = self.client.get("/shop/orders/7/")

        self.assertContains(response, "Shipping to")
        self.assertContains(response, "No delivery address recorded.")

    def test_cancel(self):
        self.log_in()
        self.api.cancel_order.return_value = order(7, status="cancelled")

        response = self.client.post("/shop/orders/7/cancel/")

        self.api.cancel_order.assert_called_once_with(7)
        self.assertRedirects(response, "/shop/orders/7/", fetch_redirect_response=False)
        self.assertIn("Order #7 was cancelled.", self.messages(response))

    def test_cancel_refused_by_the_api(self):
        self.log_in()
        self.api.cancel_order.side_effect = ApiError(400, {"detail": "Only pending orders can be cancelled."})

        response = self.client.post("/shop/orders/7/cancel/")

        self.assertRedirects(response, "/shop/orders/7/", fetch_redirect_response=False)
        self.assertIn("Only pending orders can be cancelled.", self.messages(response))

    def test_cancel_requires_post_and_login(self):
        self.assertEqual(self.client.get("/shop/orders/7/cancel/").status_code, 405)
        self.assertEqual(self.client.post("/shop/orders/7/cancel/").status_code, 302)
        self.api.cancel_order.assert_not_called()
