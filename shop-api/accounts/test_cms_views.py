from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import login
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from django.utils.html import escape
from rest_framework.authtoken.models import Token

from accounts.cms_views import (
    PENDING_KEY,
    SILENT_TRIED_KEY,
    cms_login,
    cms_logout,
    sso_authorize,
    sso_callback,
)
from accounts.models import HandoffCode, LoginSession
from accounts.services import mint_code, redeem_code
from config.fixture_secrets import USER_PASSWORD
from store.tests.factories import make_user

STOREFRONT = "http://shop.test:8080"
SHOP_API = "http://api.test:8001"
CMS = HandoffCode.Audience.CMS
EXPIRED = "Your sign-in link has expired. Sign in below."
NO_ACCESS = "Your account doesn't have access to the CMS."


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def without_query(url: str) -> str:
    return url.split("?", 1)[0]


@override_settings(STOREFRONT_URL=STOREFRONT, SHOP_API_PUBLIC_URL=SHOP_API)
class CmsSsoTestCase(TestCase):
    def setUp(self):
        self.session = SessionStore()

    def request(self, method: str, path: str, data=None, *, user=None, csrf_checks: bool = False):
        """A request carrying this test's session and real message storage, signed in as `user` if given."""
        request = getattr(RequestFactory(), method)(path, data or {})
        request.session = self.session
        request._messages = FallbackStorage(request)
        request.user = AnonymousUser()
        request._dont_enforce_csrf_checks = not csrf_checks
        if user is not None:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # sets request.user
        return request

    def messages(self, request) -> list[str]:
        return [str(message) for message in get_messages(request)]

    def begin_silently(self, next_url: str = "/cms/pages/") -> str:
        """Run the silent begin and return the state it sent to the storefront."""
        response = cms_login(self.request("get", "/cms/login/", {"next": next_url}))
        return query(response["Location"])["state"]


class SilentBeginTests(CmsSsoTestCase):
    def test_anonymous_get_stores_state_and_asks_the_storefront(self):
        response = cms_login(self.request("get", "/cms/login/", {"next": "/cms/pages/4/edit/"}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(without_query(response["Location"]), f"{STOREFRONT}/account/sso/authorize/")
        state = query(response["Location"])["state"]
        self.assertEqual(self.session[PENDING_KEY], {"state": state, "next": "/cms/pages/4/edit/"})
        self.assertTrue(self.session[SILENT_TRIED_KEY])

    def test_the_flag_stops_a_second_attempt(self):
        self.begin_silently()

        response = cms_login(self.request("get", "/cms/login/", {"next": "/cms/"}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response.render(), 'name="password"')

    def test_off_site_next_is_ignored(self):
        for target in ("https://evil.example/", "//evil.example/", f"{SHOP_API}.evil.example/"):
            with self.subTest(target):
                self.session = SessionStore()

                self.begin_silently(target)

                self.assertEqual(self.session[PENDING_KEY]["next"], "/cms/")

    def test_storefront_next_is_allowed(self):
        self.begin_silently(f"{STOREFRONT}/shop/")

        self.assertEqual(self.session[PENDING_KEY]["next"], f"{STOREFRONT}/shop/")

    def test_signed_in_staff_get_no_silent_attempt(self):
        response = cms_login(self.request("get", "/cms/login/", {"next": "/cms/"}, user=make_user(is_staff=True)))

        self.assertEqual(response["Location"], "/cms/")
        self.assertNotIn(PENDING_KEY, self.session)


class CallbackTests(CmsSsoTestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_user(is_staff=True)

    def test_valid_code_signs_in_and_goes_to_next(self):
        state = self.begin_silently("/cms/pages/4/edit/")
        code = mint_code(self.staff, CMS, state)
        request = self.request("get", "/cms/sso/callback/", {"code": code, "state": state})

        response = sso_callback(request)

        self.assertEqual(response["Location"], "/cms/pages/4/edit/")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(request.user, self.staff)
        self.assertEqual(self.session["_auth_user_id"], str(self.staff.pk))
        self.assertNotIn(PENDING_KEY, self.session)
        self.assertEqual(self.messages(request), [])

    def test_state_mismatch_is_rejected_and_spends_the_code(self):
        self.begin_silently()
        attackers_state = "attackers-state"
        code = mint_code(self.staff, CMS, attackers_state)
        request = self.request("get", "/cms/sso/callback/", {"code": code, "state": attackers_state})

        response = sso_callback(request)

        self.assertEqual(response["Location"], "/cms/login/")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertFalse(request.user.is_authenticated)
        self.assertEqual(self.messages(request), [EXPIRED])
        self.assertIsNone(redeem_code(code, CMS, attackers_state))
        self.assertNotIn(PENDING_KEY, self.session)

    def test_callback_without_a_pending_state_is_rejected(self):
        code = mint_code(self.staff, CMS, "some-state")
        request = self.request("get", "/cms/sso/callback/", {"code": code, "state": "some-state"})

        response = sso_callback(request)

        self.assertEqual(response["Location"], "/cms/login/")
        self.assertFalse(request.user.is_authenticated)
        self.assertTrue(self.session[SILENT_TRIED_KEY])
        self.assertIsNone(redeem_code(code, CMS, "some-state"))

    def test_overlong_state_is_rejected(self):
        long_state = "s" * 129
        self.session[PENDING_KEY] = {"state": long_state, "next": "/cms/"}
        code = mint_code(self.staff, CMS, long_state)
        request = self.request("get", "/cms/sso/callback/", {"code": code, "state": long_state})

        sso_callback(request)

        self.assertFalse(request.user.is_authenticated)

    def test_customer_code_is_rejected(self):
        state = self.begin_silently()
        code = mint_code(make_user(), HandoffCode.Audience.STOREFRONT, state)
        request = self.request("get", "/cms/sso/callback/", {"code": code, "state": state})

        response = sso_callback(request)

        self.assertEqual(without_query(response["Location"]), "/cms/login/")
        self.assertFalse(request.user.is_authenticated)
        self.assertEqual(self.messages(request), [EXPIRED])

    def test_reused_code_is_rejected(self):
        state = self.begin_silently()
        code = mint_code(self.staff, CMS, state)
        sso_callback(self.request("get", "/cms/sso/callback/", {"code": code, "state": state}))
        self.session = SessionStore()
        state = self.begin_silently()
        request = self.request("get", "/cms/sso/callback/", {"code": code, "state": state})

        sso_callback(request)

        self.assertFalse(request.user.is_authenticated)

    def test_storefront_errors_show_the_form_with_one_message_and_keep_next(self):
        cases = {
            "login_required": [],
            "access_denied": [NO_ACCESS],
            "temporarily_unavailable": ["We couldn't sign you in from the storefront. Sign in below."],
            "something_else": [EXPIRED],
        }
        for error, expected in cases.items():
            with self.subTest(error):
                self.session = SessionStore()
                state = self.begin_silently("/cms/pages/")
                request = self.request("get", "/cms/sso/callback/", {"error": error, "state": state})

                response = sso_callback(request)

                self.assertEqual(response["Location"], "/cms/login/?next=%2Fcms%2Fpages%2F")
                self.assertEqual(self.messages(request), expected)
                self.assertTrue(self.session[SILENT_TRIED_KEY])


class PasswordLoginTests(CmsSsoTestCase):
    def post_credentials(self, user, next_url: str = "/cms/pages/"):
        data = {"username": user.username, "password": USER_PASSWORD, "next": next_url}
        request = self.request("post", "/cms/login/", data)
        return request, cms_login(request)

    def test_staff_sign_in_bounces_to_the_storefront_begin(self):
        staff = make_user(is_staff=True)

        request, response = self.post_credentials(staff)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(without_query(response["Location"]), f"{STOREFRONT}/account/sso/begin/")
        self.assertEqual(query(response["Location"]), {"next": f"{SHOP_API}/cms/pages/"})
        self.assertEqual(request.user, staff)

    def test_off_site_next_is_ignored(self):
        _, response = self.post_credentials(make_user(is_staff=True), "https://evil.example/")

        self.assertEqual(query(response["Location"]), {"next": f"{SHOP_API}/cms/"})

    def test_customer_is_refused_on_the_form_and_not_left_signed_in(self):
        customer = make_user()

        request, response = self.post_credentials(customer)

        self.assertEqual(response.status_code, 200)
        content = response.render().content.decode()
        self.assertIn(f'<li class="error">{escape(NO_ACCESS)}</li>', content)
        self.assertIn(f'value="{customer.username}"', content)
        self.assertFalse(request.user.is_authenticated)
        self.assertNotIn("_auth_user_id", self.session)
        self.assertFalse(LoginSession.objects.filter(user=customer).exists())

    def test_wrong_password_is_wagtails_own_form(self):
        staff = make_user(is_staff=True)
        request = self.request("post", "/cms/login/", {"username": staff.username, "password": "wrong"})

        response = cms_login(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(request.user.is_authenticated)


class LogoutTests(CmsSsoTestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_user(is_staff=True)
        Token.objects.create(user=self.staff)

    def test_logout_deletes_the_token_and_bounces_through_the_storefront(self):
        request = self.request("post", "/cms/logout/", user=self.staff)

        response = cms_logout(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(without_query(response["Location"]), f"{STOREFRONT}/account/sso/logout/")
        self.assertEqual(query(response["Location"]), {"next": f"{SHOP_API}/cms/login/"})
        self.assertFalse(Token.objects.filter(user=self.staff).exists())
        self.assertFalse(LoginSession.objects.filter(user=self.staff).exists())
        self.assertFalse(request.user.is_authenticated)
        self.assertTrue(self.session[SILENT_TRIED_KEY])
        # Wagtail's messages carry trailing markup whitespace from its message template.
        self.assertEqual([text.strip() for text in self.messages(request)], ["You have been successfully logged out."])

    def test_get_does_not_log_out(self):
        request = self.request("get", "/cms/logout/", user=self.staff)

        response = cms_logout(request)

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Token.objects.filter(user=self.staff).exists())
        self.assertTrue(request.user.is_authenticated)
        self.assertIn("_auth_user_id", self.session)
        self.assertEqual(self.messages(request), [])

    def test_post_without_a_csrf_token_does_not_log_out(self):
        request = self.request("post", "/cms/logout/", user=self.staff, csrf_checks=True)

        response = cms_logout(request)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Token.objects.filter(user=self.staff).exists())
        self.assertTrue(request.user.is_authenticated)


class AuthorizeTests(CmsSsoTestCase):
    def authorize(self, params: dict[str, str], user=None):
        response = sso_authorize(self.request("get", "/cms/sso/authorize/", params, user=user))
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        return response

    def test_anonymous_gets_login_required(self):
        response = self.authorize({"state": "s1"})

        self.assertEqual(without_query(response["Location"]), f"{STOREFRONT}/account/sso/callback/")
        self.assertEqual(query(response["Location"]), {"error": "login_required", "state": "s1"})

    def test_customer_gets_access_denied(self):
        response = self.authorize({"state": "s1"}, user=make_user())

        self.assertEqual(query(response["Location"]), {"error": "access_denied", "state": "s1"})
        self.assertFalse(HandoffCode.objects.exists())

    def test_staff_gets_a_storefront_code_at_the_fixed_callback(self):
        staff = make_user(is_staff=True)

        response = self.authorize(
            {"state": "s1", "next": "https://evil.example/", "redirect_uri": "https://evil.example/"}, user=staff
        )

        self.assertEqual(without_query(response["Location"]), f"{STOREFRONT}/account/sso/callback/")
        params = query(response["Location"])
        self.assertEqual(set(params), {"code", "state"})
        self.assertEqual(params["state"], "s1")
        self.assertEqual(redeem_code(params["code"], HandoffCode.Audience.STOREFRONT, "s1"), staff)

    def test_missing_or_overlong_state_is_a_bad_request(self):
        staff = make_user(is_staff=True)
        for params in ({}, {"state": ""}, {"state": "s" * 129}):
            with self.subTest(params):
                response = sso_authorize(self.request("get", "/cms/sso/authorize/", params, user=staff))

                self.assertEqual(response.status_code, 400)
        self.assertFalse(HandoffCode.objects.exists())
