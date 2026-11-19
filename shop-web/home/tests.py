from types import SimpleNamespace
from unittest.mock import create_autospec

from django.test import RequestFactory
from wagtail.models import Page, Site

from home.models import HomePage, StandardPage
from storefront.api import ApiError, ShopApi
from storefront.tests.helpers import StorefrontTestCase, page, product


class HomePageContextTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.request = RequestFactory().get("/")

    def context(self, home: HomePage, api) -> dict:
        self.request.shop_api = api
        return home.get_context(self.request)

    def test_loads_the_newest_products(self):
        api = create_autospec(ShopApi, instance=True)
        api.list_products.return_value = page([product(1), product(2)])

        context = self.context(HomePage(title="Home", featured_count=2), api)

        api.list_products.assert_called_once_with({"page_size": 2})
        self.assertEqual([item["id"] for item in context["featured_products"]], [1, 2])

    def test_zero_featured_count_skips_the_api(self):
        api = create_autospec(ShopApi, instance=True)

        context = self.context(HomePage(title="Home", featured_count=0), api)

        api.list_products.assert_not_called()
        self.assertEqual(context["featured_products"], [])

    def test_api_failure_flags_the_shop_as_unavailable(self):
        api = create_autospec(ShopApi, instance=True)
        api.list_products.side_effect = ApiError(503, None)

        context = self.context(HomePage(title="Home"), api)

        self.assertEqual(context["featured_products"], [])
        self.assertTrue(context["shop_unavailable"])

    def test_works_without_an_api_client(self):
        context = HomePage(title="Home").get_context(SimpleNamespace(GET={}, path="/"))

        self.assertEqual(context["featured_products"], [])


class HomePageRenderTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        root = Page.get_first_root_node()
        self.home = root.add_child(instance=HomePage(title="Home", slug="home-test", hero_title="Hello shoppers"))
        self.home.add_child(instance=StandardPage(title="About us", slug="about", show_in_menus=True))
        Site.objects.update(root_page=self.home)

    def test_renders_hero_products_and_menu_pages(self):
        self.api.list_products.return_value = page([product(1, name="Sencha")])

        response = self.client.get("/")

        self.assertContains(response, "Hello shoppers")
        self.assertContains(response, "Sencha")
        self.assertContains(response, "About us")

    def test_shows_a_notice_when_the_shop_is_down(self):
        self.api.list_products.side_effect = ApiError(503, None)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Products can't be loaded right now.")
