from unittest.mock import create_autospec

from django.core.cache import cache
from django.test import override_settings

from home.cms import EMPTY_NAVIGATION, navigation, resolve_page
from storefront.api import ApiError, ShopApi
from storefront.tests.helpers import StorefrontTestCase, page, product


def cms_page(page_type: str, fields: dict, **overrides) -> dict:
    return {
        "kind": "page",
        "page": {
            "id": 3,
            "type": page_type,
            "title": "Home",
            "seo_title": "",
            "search_description": "",
            "url": "/",
            "fields": fields,
            **overrides,
        },
    }


def home_page(**fields) -> dict:
    return cms_page(
        "home.HomePage",
        {"hero_title": "Hello shoppers", "intro_html": "<p>Fresh <b>tea</b> daily.</p>", "featured_count": 4, **fields},
    )


def standard_page(body_html: str = "<p>We sell tea.</p>") -> dict:
    return cms_page("home.StandardPage", {"body_html": body_html}, id=4, title="About us", url="/about/")


class HomePageTests(StorefrontTestCase):
    def test_renders_hero_intro_products_and_payment_logos(self):
        self.api.get_cms_page.return_value = home_page(featured_count=2)
        self.api.list_products.return_value = page([product(1, name="Sencha"), product(2, name="Matcha")])

        response = self.client.get("/")

        self.api.get_cms_page.assert_called_once_with("/")
        self.api.list_products.assert_called_once_with({"page_size": 2})
        self.assertTemplateUsed(response, "home/home_page.html")
        self.assertContains(response, "Hello shoppers")
        self.assertContains(response, "<p>Fresh <b>tea</b> daily.</p>", html=True)
        self.assertContains(response, "Sencha")
        self.assertContains(response, "Matcha")
        self.assertContains(response, "Payment methods")
        self.assertContains(response, 'alt="GCash"')
        self.assertContains(response, 'alt="Visa"')

    def test_zero_featured_count_skips_the_api_and_the_section(self):
        self.api.get_cms_page.return_value = home_page(featured_count=0)

        response = self.client.get("/")

        self.api.list_products.assert_not_called()
        self.assertNotContains(response, "New arrivals")
        self.assertContains(response, "Payment methods")

    def test_shows_a_notice_when_the_shop_is_down(self):
        self.api.get_cms_page.return_value = home_page()
        self.api.list_products.side_effect = ApiError(503, None)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Products can't be loaded right now.")


class StandardPageTests(StorefrontTestCase):
    def test_renders_title_and_body(self):
        self.api.get_cms_page.return_value = standard_page('<p>Read our <a href="/shipping/">shipping</a> notes.</p>')

        response = self.client.get("/about/")

        self.api.get_cms_page.assert_called_once_with("/about/")
        self.assertTemplateUsed(response, "home/standard_page.html")
        self.assertContains(response, "<h1>About us</h1>", html=True)
        self.assertContains(response, '<a href="/shipping/">shipping</a>', html=True)
        self.api.list_products.assert_not_called()

    def test_nested_path_is_sent_with_both_slashes(self):
        self.api.get_cms_page.return_value = standard_page()

        self.client.get("/help/shipping/")

        self.api.get_cms_page.assert_called_once_with("/help/shipping/")


class CmsPageOutcomeTests(StorefrontTestCase):
    def test_redirect_payloads_become_301_or_302(self):
        for permanent, status in ((True, 301), (False, 302)):
            with self.subTest(permanent=permanent):
                cache.clear()
                self.api.get_cms_page.return_value = {"kind": "redirect", "location": "/about/", "permanent": permanent}

                response = self.client.get("/old-about/")

                self.assertEqual(response.status_code, status)
                self.assertEqual(response["Location"], "/about/")

    def test_api_404_renders_the_not_found_page(self):
        self.api.get_cms_page.side_effect = ApiError(404, {"detail": "Not found."})

        response = self.client.get("/missing/")

        self.assertContains(response, "Page not found", status_code=404)

    def test_api_503_renders_the_error_page(self):
        self.api.get_cms_page.side_effect = ApiError(503, {"detail": "The shop service is unavailable."})

        response = self.client.get("/about/")

        self.assertTemplateUsed(response, "storefront/api_error.html")
        self.assertContains(response, "Shop temporarily unavailable", status_code=503)

    def test_unknown_page_type_is_not_found(self):
        self.api.get_cms_page.return_value = cms_page("blog.BlogPage", {})

        with self.assertLogs("home.views", "WARNING") as logs:
            response = self.client.get("/")

        self.assertContains(response, "Page not found", status_code=404)
        self.assertIn("blog.BlogPage", logs.output[0])


class RevokedTokenTests(StorefrontTestCase):
    """A visitor whose token shop-api has revoked (say, signed out of the CMS elsewhere) still gets public content."""

    def setUp(self):
        super().setUp()
        self.token_api = create_autospec(ShopApi, instance=True)
        revoked = ApiError(401, {"detail": "Invalid token."})
        self.token_api.get_cms_page.side_effect = revoked
        self.token_api.get_cms_navigation.side_effect = revoked
        self.token_api.list_products.side_effect = revoked
        self.api_class.side_effect = lambda url, *, token, timeout: self.token_api if token else self.api
        self.log_in(token="revoked-token")

    def test_public_page_and_menu_render_instead_of_the_login_redirect(self):
        self.api.get_cms_page.return_value = standard_page()
        self.api.get_cms_navigation.return_value = {
            "home_url": "/welcome/",
            "items": [{"id": 4, "title": "About us", "url": "/about/"}],
        }

        response = self.client.get("/about/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>About us</h1>", html=True)
        self.assertContains(response, '<a class="brand" href="/welcome/">')
        self.assertContains(response, '<a href="/about/">About us</a>')

    def test_home_page_products_come_from_the_public_client(self):
        self.api.get_cms_page.return_value = home_page(featured_count=1)
        self.api.list_products.return_value = page([product(1, name="Sencha")])

        response = self.client.get("/")

        self.assertContains(response, "Sencha")


class CmsCacheTests(StorefrontTestCase):
    def test_second_request_within_the_ttl_is_served_from_the_cache(self):
        self.api.get_cms_page.return_value = standard_page()

        self.client.get("/about/")
        response = self.client.get("/about/")

        self.assertContains(response, "We sell tea.")
        self.api.get_cms_page.assert_called_once_with("/about/")

    def test_paths_are_cached_separately(self):
        self.api.get_cms_page.return_value = standard_page()

        self.client.get("/about/")
        self.client.get("/faq/")

        self.assertEqual(self.api.get_cms_page.call_count, 2)

    def test_errors_are_not_cached(self):
        self.api.get_cms_page.side_effect = [ApiError(503, None), standard_page()]

        first = self.client.get("/about/")
        second = self.client.get("/about/")

        self.assertEqual(first.status_code, 503)
        self.assertContains(second, "We sell tea.")
        self.assertEqual(self.api.get_cms_page.call_count, 2)

    @override_settings(CMS_CACHE_SECONDS=0)
    def test_the_ttl_comes_from_settings(self):
        self.api.get_cms_page.return_value = standard_page()

        self.client.get("/about/")
        self.client.get("/about/")

        self.assertEqual(self.api.get_cms_page.call_count, 2)


class ResolvePageTests(StorefrontTestCase):
    def test_caches_a_successful_payload_for_the_ttl(self):
        self.api.get_cms_page.return_value = standard_page()

        first = resolve_page(self.api, cache, "/about/", 60)
        second = resolve_page(self.api, cache, "/about/", 60)

        self.assertEqual(first, second)
        self.api.get_cms_page.assert_called_once_with("/about/")

    def test_errors_propagate(self):
        self.api.get_cms_page.side_effect = ApiError(404, None)

        with self.assertRaises(ApiError):
            resolve_page(self.api, cache, "/missing/", 60)


class NavigationTests(StorefrontTestCase):
    def test_caches_a_successful_payload(self):
        menu = {"home_url": "/", "items": [{"id": 4, "title": "About us", "url": "/about/"}]}
        self.api.get_cms_navigation.return_value = menu

        self.assertEqual(navigation(self.api, cache, 60), menu)
        self.assertEqual(navigation(self.api, cache, 60), menu)
        self.api.get_cms_navigation.assert_called_once_with()

    def test_failure_gives_an_empty_menu_and_is_not_cached(self):
        self.api.get_cms_navigation.side_effect = [ApiError(503, None), {"home_url": "/", "items": []}]

        self.assertEqual(navigation(self.api, cache, 60), EMPTY_NAVIGATION)
        navigation(self.api, cache, 60)

        self.assertEqual(self.api.get_cms_navigation.call_count, 2)
