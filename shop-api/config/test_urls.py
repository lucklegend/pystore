"""The real URLconf, end to end with the test client."""
import tempfile
from pathlib import Path
from types import ModuleType

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import Resolver404, resolve, reverse
from wagtail.models import Page, Site

from accounts.cms_views import cms_login, cms_logout, sso_authorize, sso_callback
from accounts.views import HandoffRedeemView, HandoffView, LogoutView
from config.urls import media_patterns
from home.models import StandardPage
from home.views import NavigationView, ResolvePageView, storefront_redirect
from store.tests.factories import make_user

STOREFRONT = "http://shop.test:8080"
# What Wagtail's rich-text editor posts for `Hello`.
CONTENT_STATE = '{"blocks":[{"key":"a","text":"Hello","type":"unstyled","depth":0,"inlineStyleRanges":[],"entityRanges":[]}],"entities":[]}'


class RouteTests(TestCase):
    def test_contract_routes_resolve_to_their_views(self):
        expected = {
            "/api/cms/pages/resolve/": ResolvePageView,
            "/api/cms/navigation/": NavigationView,
            "/api/auth/handoff/": HandoffView,
            "/api/auth/handoff/redeem/": HandoffRedeemView,
            "/api/auth/logout/": LogoutView,
        }
        for path, view in expected.items():
            with self.subTest(path):
                self.assertIs(resolve(path).func.view_class, view)

    def test_cms_sso_routes_shadow_wagtails_login_and_logout(self):
        expected = {
            "/cms/login/": cms_login,
            "/cms/logout/": cms_logout,
            "/cms/sso/authorize/": sso_authorize,
            "/cms/sso/callback/": sso_callback,
        }
        for path, view in expected.items():
            with self.subTest(path):
                self.assertIs(resolve(path).func, view)
        self.assertEqual(reverse("wagtailadmin_login"), "/cms/login/")
        self.assertEqual(reverse("wagtailadmin_logout"), "/cms/logout/")

    def test_wagtail_admin_is_mounted_only_under_the_gated_prefix(self):
        self.assertEqual(settings.CMS_URL_PREFIX, "/cms/")
        self.assertEqual(reverse("wagtailadmin_home"), settings.CMS_URL_PREFIX)
        self.assertEqual(resolve("/cms/").url_name, "wagtailadmin_home")
        # A second mount would sit outside CmsStaffOnlyMiddleware, so no admin route may resolve elsewhere.
        for name, args in (("wagtailadmin_explore_root", ()), ("wagtailadmin_pages:edit", (1,)), ("wagtailadmin_password_reset", ())):
            with self.subTest(name):
                self.assertTrue(reverse(name, args=args).startswith(settings.CMS_URL_PREFIX))
        for path in ("/pages/", "/password_reset/", "/images/"):
            with self.subTest(path):
                self.assertEqual(resolve(path).url_name, "wagtail_serve")

    def test_documents_are_served_by_wagtail(self):
        self.assertEqual(resolve("/documents/1/file.pdf").url_name, "wagtaildocs_serve")

    def test_wagtail_serve_reverses_to_the_storefront_redirect(self):
        self.assertEqual(reverse("wagtail_serve", args=("about/",)), "/about/")
        self.assertEqual(reverse("wagtail_serve", args=("",)), "/")
        self.assertIs(resolve("/about/").func, storefront_redirect)


@override_settings(STOREFRONT_URL=STOREFRONT)
class StorefrontRedirectTests(TestCase):
    def test_pages_redirect_to_the_storefront(self):
        for path, location in (("/", f"{STOREFRONT}/"), ("/about/", f"{STOREFRONT}/about/"), ("/a/b-c/", f"{STOREFRONT}/a/b-c/")):
            with self.subTest(path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], location)

    def test_paths_that_could_leave_the_storefront_do_not_route_to_the_redirect(self):
        for path in ("//evil.com/", "///evil.com/", "/evil.com/", "/http://evil.com/", "/http:/evil.com/", "/\\evil.com/", "/a//b/", "/@evil.com/", "/a:b/"):
            with self.subTest(path):
                with self.assertRaises(Resolver404):
                    resolve(path)
                self.assertEqual(self.client.request(REQUEST_METHOD="GET", PATH_INFO=path).status_code, 404)

    def test_the_location_always_starts_with_the_storefront(self):
        for path in ("/", "/x/", "/x/y/", "/ünï/", "/a_b/c-d/"):
            with self.subTest(path):
                self.assertTrue(self.client.get(path)["Location"].startswith(f"{STOREFRONT}/"))


class CmsAccessTests(TestCase):
    def test_superuser_reaches_the_dashboard_and_sees_every_menu(self):
        superuser = get_user_model().objects.create_superuser("root", "root@example.com", "x")
        self.client.force_login(superuser)

        response = self.client.get("/cms/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"url": "/cms/users/"')
        self.assertContains(response, '"name": "settings"')

    def test_moderators_reach_the_dashboard_but_not_users_or_settings(self):
        moderator = make_user(is_staff=True)
        self.assertTrue(moderator.groups.filter(name="Moderators").exists())
        self.client.force_login(moderator)

        response = self.client.get("/cms/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '"url": "/cms/users/"')
        self.assertNotContains(response, '"name": "settings"')
        self.assertEqual(self.client.get("/cms/users/").status_code, 302)  # Wagtail refuses the permission

    def test_moderators_can_publish(self):
        moderator = make_user(is_staff=True)
        root = Site.objects.get(is_default_site=True).root_page
        draft = root.add_child(instance=StandardPage(title="Draft", slug="draft", live=False))
        self.assertTrue(draft.permissions_for_user(moderator).can_publish())
        self.client.force_login(moderator)

        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=(draft.pk,)),
            {
                "title": "Draft",
                "slug": "draft",
                "body": CONTENT_STATE,
                "action-publish": "Publish",
                "comments-TOTAL_FORMS": "0",
                "comments-INITIAL_FORMS": "0",
                "comments-MIN_NUM_FORMS": "0",
                "comments-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertTrue(draft.live)

    def test_a_customer_is_signed_out_and_sent_to_the_cms_login(self):
        customer = make_user()
        self.client.force_login(customer)

        response = self.client.get("/cms/")

        self.assertRedirects(response, "/cms/login/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_staff_user_demoted_mid_session_is_bounced_on_the_next_request(self):
        staff = make_user(is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/cms/").status_code, 200)

        get_user_model().objects.filter(pk=staff.pk).update(is_staff=False)  # skips signals
        response = self.client.get("/cms/")

        self.assertRedirects(response, "/cms/login/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_an_anonymous_visitor_is_sent_to_the_login_page(self):
        response = self.client.get("/cms/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/cms/login/"))


@override_settings(STOREFRONT_URL=STOREFRONT)
class NavigationUrlTests(TestCase):
    def test_a_live_page_has_a_url_in_the_navigation(self):
        root = Site.objects.get(is_default_site=True).root_page
        root.add_child(instance=StandardPage(title="About", slug="about", show_in_menus=True))

        response = self.client.get("/api/cms/navigation/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["url"] for item in response.json()["items"]], ["/about/"])
        self.assertEqual(Page.objects.get(slug="about").url, "/about/")


class MediaPatternsTests(TestCase):
    def test_no_patterns_without_debug(self):
        self.assertEqual(media_patterns(False, "http://api.test/media/", "/srv/media"), [])

    def test_no_patterns_when_media_url_has_no_path(self):
        # An empty prefix would route every URL to the file server.
        self.assertEqual(media_patterns(True, "http://api.test", "/srv/media"), [])

    def test_the_prefix_comes_from_the_path_of_an_absolute_media_url(self):
        (pattern,) = media_patterns(True, "http://api.test:8001/uploads/", "/srv/media")
        self.assertTrue(pattern.resolve("uploads/a/b.png"))
        self.assertFalse(pattern.resolve("media/a/b.png"))

    def test_an_uploaded_file_is_served_with_nosniff(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "images").mkdir()
            (Path(root) / "images" / "hello.txt").write_text("hi")
            urlconf = ModuleType("media_urlconf")
            urlconf.urlpatterns = media_patterns(True, settings.MEDIA_URL, root)

            with override_settings(ROOT_URLCONF=urlconf):
                response = self.client.get("/media/images/hello.txt")
                body = b"".join(response.streaming_content)
                missing = self.client.get("/media/images/missing.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, b"hi")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(missing.status_code, 404)
