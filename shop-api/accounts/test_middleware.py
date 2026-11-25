from django.conf import settings
from django.contrib.auth import get_user, get_user_model, login, update_session_auth_hash
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from accounts.cms_views import SILENT_TRIED_KEY
from accounts.middleware import CmsStaffOnlyMiddleware
from accounts.models import HandoffCode
from accounts.services import SESSION_EPOCH_KEY, sign_out_everywhere
from store.tests.factories import make_user

User = get_user_model()

PASSED = HttpResponse("passed")
STATE = "state-from-the-storefront"


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

    def next_request(self, path: str, earlier):
        """The browser's next GET, carrying `earlier`'s session as saved and read back from the database."""
        earlier.session.save()
        request = RequestFactory().get(path)
        request.session = SessionStore(earlier.session.session_key)
        request._messages = FallbackStorage(request)
        request.user = get_user(request)
        return request

    def assert_signed_out(self, request, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/cms/login/")
        self.assertFalse(request.user.is_authenticated)
        self.assertNotIn("_auth_user_id", request.session)

    def assert_rejected(self, request, response):
        """Signed out for lacking access, with one message and no silent sign-in to contradict it."""
        self.assert_signed_out(request, response)
        self.assertEqual(
            [str(message) for message in get_messages(request)],
            ["Your account no longer has access to the CMS."],
        )
        self.assertIs(request.session.get(SILENT_TRIED_KEY), True)

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

    def test_signing_out_everywhere_ends_a_session_whose_key_rotated_since_login(self):
        user = make_user(is_staff=True)
        request = self.request("/cms/", user)
        signed_in_key = request.session.session_key
        update_session_auth_hash(request, user)  # what saving Wagtail's account settings does
        self.assertNotEqual(request.session.session_key, signed_in_key)
        rotated = self.next_request("/cms/pages/", request)
        self.assertIs(self.middleware(rotated), PASSED)

        sign_out_everywhere(user)
        after = self.next_request("/cms/pages/", rotated)
        self.assertTrue(after.user.is_authenticated)  # the rotated session itself survived the logout
        response = self.middleware(after)

        self.assert_signed_out(after, response)
        self.assertEqual(list(get_messages(after)), [])  # the login page's silent attempt decides what to show
        self.assertNotIn(SILENT_TRIED_KEY, after.session)

    def test_signing_out_everywhere_leaves_other_users_sessions_alone(self):
        user, other = make_user(is_staff=True), make_user(is_staff=True)
        other_request = self.request("/cms/", other)
        update_session_auth_hash(other_request, other)

        sign_out_everywhere(user)

        self.assertIs(self.middleware(self.next_request("/cms/pages/", other_request)), PASSED)

    def test_signing_in_after_signing_out_everywhere_passes(self):
        user = make_user(is_staff=True)
        sign_out_everywhere(user)

        self.assertIs(self.middleware(self.request("/cms/pages/", user)), PASSED)

    def test_session_without_an_epoch_is_signed_out(self):
        request = self.request("/cms/", make_user(is_staff=True))
        del request.session[SESSION_EPOCH_KEY]  # e.g. signed in before epochs existed

        self.assert_signed_out(request, self.middleware(request))

    def test_exempt_route_signs_out_a_stale_session_and_lets_the_view_run_anonymously(self):
        user = make_user(is_staff=True)
        request = self.next_request("/cms/login/", self.request("/cms/", user))

        sign_out_everywhere(user)
        response = self.middleware(request)

        self.assertIs(response, PASSED)
        self.assertFalse(request.user.is_authenticated)
        self.assertNotIn("_auth_user_id", request.session)

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


class SignOutEpochRequestTests(TestCase):
    """Through the real URLconf and middleware stack: the admin check runs once the URL is resolved,
    and on exempt CMS routes it is the view that must see the signed-out visitor."""

    def rotated_session(self, user) -> str:
        """Sign `user` in on self.client, then rotate the key as /admin/password_change/ does. Returns the new key."""
        self.client.force_login(user)
        request = RequestFactory().get("/")
        request.session = SessionStore(self.client.session.session_key)
        request.user = user
        update_session_auth_hash(request, user)
        request.session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = request.session.session_key
        return request.session.session_key

    def test_signing_out_everywhere_ends_an_admin_session_whose_key_rotated_since_login(self):
        user = make_user(is_staff=True)
        key = self.rotated_session(user)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

        sign_out_everywhere(user)
        self.assertTrue(Session.objects.filter(session_key=key).exists())  # untracked since it rotated
        response = self.client.get("/admin/store/")

        self.assertRedirects(response, "/admin/login/?next=/admin/store/", fetch_redirect_response=False)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertNotIn(SILENT_TRIED_KEY, self.client.session)
        self.assertEqual(list(get_messages(response.wsgi_request)), [])

    def test_signing_out_everywhere_leaves_other_users_admin_sessions_alone(self):
        user, other = make_user(is_staff=True), make_user(is_staff=True)
        self.rotated_session(other)

        sign_out_everywhere(user)

        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_signing_out_everywhere_stops_a_rotated_session_minting_a_storefront_code(self):
        user = make_user(is_staff=True)
        key = self.rotated_session(user)

        sign_out_everywhere(user)
        response = self.client.get("/cms/sso/authorize/", {"state": STATE})

        self.assertRedirects(
            response,
            f"{settings.STOREFRONT_URL}/account/sso/callback/?error=login_required&state={STATE}",
            fetch_redirect_response=False,
        )
        self.assertFalse(HandoffCode.objects.exists())
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_a_current_staff_session_still_gets_a_storefront_code(self):
        user = make_user(is_staff=True)
        self.rotated_session(user)

        response = self.client.get("/cms/sso/authorize/", {"state": STATE})

        self.assertEqual(response.status_code, 302)
        self.assertIn("code=", response["Location"])
        self.assertEqual(HandoffCode.objects.get().user, user)

    def test_api_does_not_accept_a_session(self):
        user = make_user()
        self.rotated_session(user)

        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, 401)
