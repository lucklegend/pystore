from unittest.mock import create_autospec, patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.test import override_settings

from storefront.api import ApiError, ShopApi
from storefront.session import TOKEN_KEY, USER_KEY
from storefront.sso import PENDING_KEY

from .helpers import CUSTOMER, STAFF, StorefrontTestCase

CMS = "http://cms.example:8001"
BEGIN = "/account/sso/begin/"
AUTHORIZE = "/account/sso/authorize/"
CALLBACK = "/account/sso/callback/"
LOGOUT = "/account/sso/logout/"
CMS_PAGE = f"{CMS}/cms/pages/4/edit/"


def split_redirect(response) -> tuple[str, dict[str, str]]:
    """The redirect target without its query, and the query as single values."""
    parts = urlsplit(response["Location"])
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else parts.path, query


@override_settings(SHOP_API_PUBLIC_URL=CMS)
class SsoBeginTests(StorefrontTestCase):
    def test_stores_state_and_next_and_redirects_to_the_cms(self):
        response = self.client.get(BEGIN, {"next": CMS_PAGE})

        target, query = split_redirect(response)
        self.assertEqual(target, f"{CMS}/cms/sso/authorize/")
        self.assertEqual(self.client.session[PENDING_KEY], {"state": query["state"], "next": CMS_PAGE})

    def test_each_begin_gets_a_new_state(self):
        first = split_redirect(self.client.get(BEGIN))[1]["state"]
        second = split_redirect(self.client.get(BEGIN))[1]["state"]

        self.assertNotEqual(first, second)
        self.assertEqual(self.client.session[PENDING_KEY]["state"], second)

    def test_keeps_a_storefront_next(self):
        self.client.get(BEGIN, {"next": "/shop/cart/"})

        self.assertEqual(self.client.session[PENDING_KEY]["next"], "/shop/cart/")

    def test_ignores_an_off_site_next(self):
        for target in ("https://evil.example/", "//evil.example/", "http://cms.example:9999/cms/"):
            with self.subTest(target=target):
                self.client.get(BEGIN, {"next": target})

                self.assertEqual(self.client.session[PENDING_KEY]["next"], "/")

    def test_requires_get(self):
        self.assertEqual(self.client.post(BEGIN).status_code, 405)


@override_settings(SHOP_API_PUBLIC_URL=CMS)
class SsoCallbackTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.handoff_api = create_autospec(ShopApi, instance=True)
        self.handoff_api.redeem_handoff.return_value = {"token": "cms-token", "user": STAFF}
        patcher = patch("storefront.views.sso.ShopApi", return_value=self.handoff_api)
        self.handoff_api_class = patcher.start()
        self.addCleanup(patcher.stop)

    def begin(self, next_url: str = CMS_PAGE) -> str:
        return split_redirect(self.client.get(BEGIN, {"next": next_url}))[1]["state"]

    def test_valid_code_signs_in_and_follows_next(self):
        state = self.begin()

        response = self.client.get(CALLBACK, {"code": "the-code", "state": state})

        self.handoff_api.redeem_handoff.assert_called_once_with("the-code", state, settings.SSO_CLIENT_SECRET)
        self.assertRedirects(response, CMS_PAGE, fetch_redirect_response=False)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.client.session[TOKEN_KEY], "cms-token")
        self.assertEqual(self.client.session[USER_KEY], STAFF)
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertEqual(self.messages(response), [])

    def test_redeems_without_the_current_session_token(self):
        self.log_in(CUSTOMER, token="customer-token")
        state = self.begin()

        self.client.get(CALLBACK, {"code": "the-code", "state": state})

        self.handoff_api_class.assert_called_once_with(settings.SHOP_API_URL, timeout=settings.SHOP_API_TIMEOUT)
        self.api.redeem_handoff.assert_not_called()
        self.assertEqual(self.client.session[TOKEN_KEY], "cms-token")

    def test_state_mismatch_is_rejected(self):
        self.begin()

        response = self.client.get(CALLBACK, {"code": "the-code", "state": "forged"})

        self.handoff_api.redeem_handoff.assert_not_called()
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.messages(response), ["That sign-in link has expired. Please log in again."])
        self.assertNotIn(TOKEN_KEY, self.client.session)

    def test_non_ascii_state_is_rejected_not_an_error(self):
        self.begin()

        response = self.client.get(CALLBACK, {"code": "the-code", "state": "état"})

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.handoff_api.redeem_handoff.assert_not_called()

    def test_missing_state_or_no_begin_is_rejected(self):
        for params in ({"code": "the-code"}, {"code": "the-code", "state": "anything"}):
            with self.subTest(params=params):
                response = self.client.get(CALLBACK, params)

                self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.handoff_api.redeem_handoff.assert_not_called()

    def test_state_is_single_use(self):
        state = self.begin()
        self.client.get(CALLBACK, {"code": "the-code", "state": state})
        self.log_out()

        response = self.client.get(CALLBACK, {"code": "the-code", "state": state})

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.handoff_api.redeem_handoff.assert_called_once()
        self.assertNotIn(TOKEN_KEY, self.client.session)

    def test_a_mismatch_also_uses_up_the_stored_state(self):
        state = self.begin()
        self.client.get(CALLBACK, {"code": "the-code", "state": "forged"})

        response = self.client.get(CALLBACK, {"code": "the-code", "state": state})

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.handoff_api.redeem_handoff.assert_not_called()

    def test_failed_redeem_still_goes_to_next_without_signing_in(self):
        for status in (400, 403, 503):
            with self.subTest(status=status):
                self.log_out()
                self.handoff_api.redeem_handoff.side_effect = ApiError(status, {"detail": "Nope."})
                state = self.begin()

                response = self.client.get(CALLBACK, {"code": "the-code", "state": state})

                self.assertRedirects(response, CMS_PAGE, fetch_redirect_response=False)
                self.assertNotIn(TOKEN_KEY, self.client.session)
                self.assertEqual(self.messages(response), [])

    def test_error_from_the_cms_goes_to_next_without_redeeming(self):
        state = self.begin()

        response = self.client.get(CALLBACK, {"error": "login_required", "state": state})

        self.handoff_api.redeem_handoff.assert_not_called()
        self.assertRedirects(response, CMS_PAGE, fetch_redirect_response=False)
        self.assertNotIn(TOKEN_KEY, self.client.session)

    def test_follows_a_storefront_next(self):
        state = self.begin("/shop/orders/")

        response = self.client.get(CALLBACK, {"code": "the-code", "state": state})

        self.assertRedirects(response, "/shop/orders/", fetch_redirect_response=False)


@override_settings(SHOP_API_PUBLIC_URL=CMS)
class SsoAuthorizeTests(StorefrontTestCase):
    CALLBACK_URL = f"{CMS}/cms/sso/callback/"

    def authorize(self) -> dict[str, str]:
        # Extra parameters try to steer the redirect; the callback URL must ignore them.
        response = self.client.get(
            AUTHORIZE, {"state": "S", "next": "https://evil.example/", "redirect_uri": "https://evil.example/"}
        )
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        target, query = split_redirect(response)
        self.assertEqual(target, self.CALLBACK_URL)
        return query

    def test_anonymous_gets_login_required(self):
        self.assertEqual(self.authorize(), {"error": "login_required", "state": "S"})
        self.api.create_handoff.assert_not_called()

    def test_staff_gets_a_code_bound_to_the_state(self):
        self.log_in(STAFF)
        self.api.create_handoff.return_value = {"code": "the-code", "expires_in": 60}

        self.assertEqual(self.authorize(), {"code": "the-code", "state": "S"})
        self.api.create_handoff.assert_called_once_with("S")

    def test_customer_gets_access_denied(self):
        self.log_in(CUSTOMER)
        self.api.create_handoff.side_effect = ApiError(403, {"detail": "Not allowed."})

        self.assertEqual(self.authorize(), {"error": "access_denied", "state": "S"})
        self.assertEqual(self.client.session[USER_KEY], CUSTOMER)

    def test_api_outage_gets_temporarily_unavailable(self):
        self.log_in(STAFF)
        self.api.create_handoff.side_effect = ApiError(503, {"detail": "Down."})

        self.assertEqual(self.authorize(), {"error": "temporarily_unavailable", "state": "S"})
        self.assertEqual(self.client.session[USER_KEY], STAFF)

    def test_dead_token_gets_login_required_and_signs_out(self):
        self.log_in(STAFF)
        self.api.create_handoff.side_effect = ApiError(401, {"detail": "Invalid token."})

        self.assertEqual(self.authorize(), {"error": "login_required", "state": "S"})
        self.assertNotIn(TOKEN_KEY, self.client.session)

    def test_requires_get(self):
        self.assertEqual(self.client.post(AUTHORIZE, {"state": "S"}).status_code, 405)


@override_settings(SHOP_API_PUBLIC_URL=CMS)
class SsoLogoutTests(StorefrontTestCase):
    CMS_LOGIN = f"{CMS}/cms/login/"

    def test_dead_token_clears_the_session(self):
        self.log_in(STAFF)
        self.api.me.side_effect = ApiError(401, {"detail": "Invalid token."})

        response = self.client.get(LOGOUT, {"next": self.CMS_LOGIN})

        self.assertRedirects(response, self.CMS_LOGIN, fetch_redirect_response=False)
        self.assertNotIn(TOKEN_KEY, self.client.session)
        self.assertNotIn(USER_KEY, self.client.session)

    def test_valid_token_keeps_the_session(self):
        self.log_in(STAFF)
        self.api.me.return_value = STAFF

        response = self.client.get(LOGOUT, {"next": self.CMS_LOGIN})

        self.assertRedirects(response, self.CMS_LOGIN, fetch_redirect_response=False)
        self.assertEqual(self.client.session[TOKEN_KEY], "secret-token")

    def test_api_outage_keeps_the_session(self):
        self.log_in(STAFF)
        self.api.me.side_effect = ApiError(503, {"detail": "Down."})

        response = self.client.get(LOGOUT, {"next": self.CMS_LOGIN})

        self.assertRedirects(response, self.CMS_LOGIN, fetch_redirect_response=False)
        self.assertEqual(self.client.session[TOKEN_KEY], "secret-token")

    def test_anonymous_skips_the_api(self):
        response = self.client.get(LOGOUT, {"next": self.CMS_LOGIN})

        self.api.me.assert_not_called()
        self.assertRedirects(response, self.CMS_LOGIN, fetch_redirect_response=False)

    def test_ignores_an_off_site_next(self):
        response = self.client.get(LOGOUT, {"next": "https://evil.example/"})

        self.assertRedirects(response, "/", fetch_redirect_response=False)
