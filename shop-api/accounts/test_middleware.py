from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from accounts.middleware import CmsStaffOnlyMiddleware
from store.tests.factories import make_user

User = get_user_model()

PASSED = HttpResponse("passed")


class CmsStaffOnlyMiddlewareTests(TestCase):
    def setUp(self):
        self.middleware = CmsStaffOnlyMiddleware(lambda request: PASSED)

    def request(self, path: str, user=None):
        """A GET carrying a real session and message storage, signed in as `user` if given."""
        request = RequestFactory().get(path)
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        request.user = AnonymousUser()
        if user is not None:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # sets request.user
        return request

    def assert_rejected(self, request, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/cms/login/")
        self.assertFalse(request.user.is_authenticated)
        self.assertNotIn("_auth_user_id", request.session)
        self.assertEqual(
            [str(message) for message in get_messages(request)],
            ["Only staff can use the CMS. Sign in with a staff account."],
        )

    def test_staff_user_passes(self):
        response = self.middleware(self.request("/cms/pages/", make_user(is_staff=True)))

        self.assertIs(response, PASSED)

    def test_superuser_passes_without_the_staff_flag(self):
        user = make_user()
        user.is_superuser = True
        user.save()

        response = self.middleware(self.request("/cms/", user))

        self.assertIs(response, PASSED)

    def test_customer_is_signed_out_and_sent_to_the_login_page(self):
        request = self.request("/cms/", make_user())

        response = self.middleware(request)

        self.assert_rejected(request, response)

    def test_staff_flag_cleared_by_queryset_update_blocks_the_next_request(self):
        user = make_user(is_staff=True)
        self.assertIs(self.middleware(self.request("/cms/", user)), PASSED)
        request = self.request("/cms/pages/", user)

        User.objects.filter(pk=user.pk).update(is_staff=False)  # no save(), no signals
        response = self.middleware(request)

        self.assertTrue(user.is_staff)  # the in-memory user is stale; the database decides
        self.assert_rejected(request, response)

    def test_deactivation_by_queryset_update_blocks_the_next_request(self):
        user = make_user(is_staff=True)
        request = self.request("/cms/", user)

        User.objects.filter(pk=user.pk).update(is_active=False)
        response = self.middleware(request)

        self.assert_rejected(request, response)

    def test_exempt_routes_let_a_customer_through(self):
        user = make_user()
        for path in (
            "/cms/login/",
            "/cms/logout/",
            "/cms/sso/authorize/",
            "/cms/sso/callback/",
            "/cms/password_reset/",
            "/cms/password_reset/done/",
            "/cms/password_reset/confirm/MQ/abc-123/",
            "/cms/password_reset/complete/",
        ):
            with self.subTest(path):
                request = self.request(path, user)

                self.assertIs(self.middleware(request), PASSED)
                self.assertTrue(request.user.is_authenticated)

    def test_exemption_matches_whole_routes_only(self):
        user = make_user()
        for path in ("/cms/login/../pages/", "/cms/sso/", "/cms/sso/authorize/extra/", "/cms/loginx/"):
            with self.subTest(path):
                request = self.request(path, user)

                self.assert_rejected(request, self.middleware(request))

    def test_paths_outside_the_cms_are_not_gated(self):
        for path in ("/api/products/", "/admin/", "/cmsx/", "/"):
            with self.subTest(path):
                self.assertIs(self.middleware(self.request(path, make_user())), PASSED)

    def test_anonymous_requests_are_left_to_wagtail(self):
        self.assertIs(self.middleware(self.request("/cms/pages/")), PASSED)

    @override_settings(CMS_URL_PREFIX="/editor/")
    def test_prefix_comes_from_settings(self):
        middleware = CmsStaffOnlyMiddleware(lambda request: PASSED)
        user = make_user()

        self.assertIs(middleware(self.request("/cms/", user)), PASSED)
        response = middleware(self.request("/editor/", user))
        self.assertEqual(response["Location"], "/editor/login/")
