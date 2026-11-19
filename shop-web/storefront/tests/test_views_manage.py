from storefront.api import ApiError

from .helpers import CUSTOMER, STAFF, StorefrontTestCase, page, product

CATEGORIES = [{"id": 1, "name": "Tea"}]


def form_data(**overrides) -> dict:
    return {"name": "Kettle", "category": "1", "description": "", "price": "30.00", "stock": "4",
            "image_url": "", "is_active": "on", **overrides}


class StaffOnlyTests(StorefrontTestCase):
    URLS = ("/shop/manage/products/", "/shop/manage/products/new/", "/shop/manage/products/1/edit/",
            "/shop/manage/products/1/delete/")

    def test_anonymous_users_are_sent_to_login(self):
        for url in self.URLS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_customers_are_forbidden(self):
        self.log_in(CUSTOMER)
        for url in self.URLS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.api.get_product.assert_not_called()


class ManageProductsTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.log_in(STAFF)
        self.api.list_categories.return_value = CATEGORIES

    def test_lists_products_by_name(self):
        self.api.list_products.return_value = page([product(1, name="Kettle", is_active=False)])

        response = self.client.get("/shop/manage/products/", {"q": " ket "})

        self.api.list_products.assert_called_once_with({"page": 1, "page_size": 20, "ordering": "name", "search": "ket"})
        self.assertContains(response, "Kettle")

    def test_create_shows_an_empty_form(self):
        response = self.client.get("/shop/manage/products/new/")

        self.assertContains(response, "New product")
        self.api.create_product.assert_not_called()

    def test_create_posts_the_payload(self):
        self.api.create_product.return_value = product(9, name="Kettle")

        response = self.client.post("/shop/manage/products/new/", form_data())

        self.api.create_product.assert_called_once_with(
            {"name": "Kettle", "category": 1, "description": "", "price": "30.00", "stock": 4, "image_url": "",
             "is_active": True}
        )
        self.assertRedirects(response, "/shop/manage/products/", fetch_redirect_response=False)
        self.assertIn("Saved Kettle.", self.messages(response))

    def test_invalid_form_does_not_call_the_api(self):
        response = self.client.post("/shop/manage/products/new/", form_data(price="-5"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("price", response.context["form"].errors)
        self.api.create_product.assert_not_called()

    def test_api_validation_errors_land_on_the_form(self):
        self.api.create_product.side_effect = ApiError(400, {"name": ["Too long."], "detail": "Check the form."})

        response = self.client.post("/shop/manage/products/new/", form_data())

        form = response.context["form"]
        self.assertEqual(form.errors["name"], ["Too long."])
        self.assertEqual(form.non_field_errors(), ["Check the form."])

    def test_edit_prefills_from_the_api(self):
        self.api.get_product.return_value = product(4, name="Old kettle", category=1, price="12.00")

        response = self.client.get("/shop/manage/products/4/edit/")

        form = response.context["form"]
        self.assertEqual(form.initial["name"], "Old kettle")
        self.assertEqual(form.initial["category"], 1)
        self.assertContains(response, "Edit Old kettle")

    def test_edit_updates_the_product(self):
        self.api.get_product.return_value = product(4)
        self.api.update_product.return_value = product(4, name="Kettle")

        response = self.client.post("/shop/manage/products/4/edit/", form_data())

        self.assertEqual(self.api.update_product.call_args.args[0], 4)
        self.assertEqual(self.api.update_product.call_args.args[1]["name"], "Kettle")
        self.api.create_product.assert_not_called()
        self.assertRedirects(response, "/shop/manage/products/", fetch_redirect_response=False)


class DeleteProductTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.log_in(STAFF)
        self.api.get_product.return_value = product(4, name="Kettle")

    def test_get_asks_for_confirmation(self):
        response = self.client.get("/shop/manage/products/4/delete/")

        self.assertContains(response, "Delete Kettle?")
        self.api.delete_product.assert_not_called()

    def test_post_deletes(self):
        response = self.client.post("/shop/manage/products/4/delete/")

        self.api.delete_product.assert_called_once_with(4)
        self.assertRedirects(response, "/shop/manage/products/", fetch_redirect_response=False)
        self.assertIn("Deleted Kettle.", self.messages(response))

    def test_ordered_products_cannot_be_deleted(self):
        self.api.delete_product.side_effect = ApiError(409, {"detail": "This product appears in orders."})

        response = self.client.post("/shop/manage/products/4/delete/")

        self.assertRedirects(response, "/shop/manage/products/4/edit/", fetch_redirect_response=False)
        self.assertIn("This product appears in orders.", self.messages(response))
