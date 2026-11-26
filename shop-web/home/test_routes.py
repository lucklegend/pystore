from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve

from home.views import cms_page
from storefront.api import ApiError
from storefront.tests.helpers import StorefrontTestCase


class CatchAllRouteTests(SimpleTestCase):
    def test_paths_reach_cms_page_with_the_path_after_the_leading_slash(self):
        for url, path in [("/", ""), ("/about/", "about/"), ("/a/b/", "a/b/")]:
            with self.subTest(url=url):
                match = resolve(url)
                self.assertIs(match.func, cms_page)
                self.assertEqual(match.args, (path,))

    def test_storefront_routes_win_over_the_catch_all(self):
        self.assertNotEqual(resolve("/shop/").func, cms_page)

    def test_settings_have_no_databases(self):
        # Django turns an empty DATABASES into a dummy default whose every query raises.
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.dummy")


class CatchAllResponseTests(StorefrontTestCase):
    def test_missing_trailing_slash_redirects(self):
        response = self.client.get("/about")

        self.assertRedirects(response, "/about/", fetch_redirect_response=False, status_code=301)
        self.api.get_cms_page.assert_not_called()

    def test_cms_admin_is_not_served_by_shop_web(self):
        self.api.get_cms_page.side_effect = ApiError(404, {"detail": "Not found."})

        response = self.client.get("/cms/")

        self.assertEqual(response.status_code, 404)
