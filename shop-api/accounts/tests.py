import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import Client, override_settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import HandoffCode
from accounts.services import mint_code, redeem_code
from accounts.views import INVALID_HANDOFF
from config.fixture_secrets import USER_PASSWORD, WRONG_PASSWORD
from store.tests.factories import make_user

User = get_user_model()

REGISTER = "/api/auth/register/"
LOGIN = "/api/auth/login/"
LOGOUT = "/api/auth/logout/"
ME = "/api/auth/me/"
HANDOFF = "/api/auth/handoff/"
REDEEM = "/api/auth/handoff/redeem/"

CMS = HandoffCode.Audience.CMS
STOREFRONT = HandoffCode.Audience.STOREFRONT
STATE = secrets.token_urlsafe(32)
CLIENT_SECRET = secrets.token_urlsafe(32)


class RegisterTests(APITestCase):
    def register(self, **overrides):
        payload = {"username": "alice", "email": "alice@example.com", "password": USER_PASSWORD, **overrides}
        return self.client.post(REGISTER, payload, format="json")

    def test_creates_user_and_returns_token(self):
        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username="alice")
        self.assertTrue(user.check_password(USER_PASSWORD))
        self.assertFalse(user.is_staff)
        self.assertEqual(response.data["token"], Token.objects.get(user=user).key)
        self.assertEqual(
            response.data["user"], {"id": user.pk, "username": "alice", "email": "alice@example.com", "is_staff": False}
        )
        self.assertNotIn("password", response.data["user"])

    def test_cannot_register_as_staff(self):
        self.register(is_staff=True)

        self.assertFalse(User.objects.get(username="alice").is_staff)

    def test_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(username="existing", email="Alice@Example.com", password=USER_PASSWORD)

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"], ["An account with this email already exists."])

    def test_requires_email(self):
        for email in ("", None):
            with self.subTest(email=email):
                payload = {"username": "alice", "password": USER_PASSWORD}
                if email is not None:
                    payload["email"] = email

                response = self.client.post(REGISTER, payload, format="json")

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("email", response.data)

    def test_rejects_weak_passwords(self):
        cases = {
            "too short": secrets.token_hex(2),
            "too common": "password",
            "all digits": str(secrets.randbelow(9 * 10**9) + 10**9),
            "like username": f"alice{secrets.randbelow(900) + 100}",
        }
        for label, password in cases.items():
            with self.subTest(label):
                response = self.register(password=password)

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertTrue(response.data["password"])
        self.assertFalse(User.objects.exists())


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", email="a@example.com", password=USER_PASSWORD)

    def test_returns_token_and_user(self):
        response = self.client.post(LOGIN, {"username": "alice", "password": USER_PASSWORD}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["token"], Token.objects.get(user=self.user).key)
        self.assertEqual(response.data["user"]["username"], "alice")

    def test_reuses_an_existing_token(self):
        token = Token.objects.create(user=self.user)

        response = self.client.post(LOGIN, {"username": "alice", "password": USER_PASSWORD}, format="json")

        self.assertEqual(response.data["token"], token.key)

    def test_wrong_password_is_400(self):
        response = self.client.post(LOGIN, {"username": "alice", "password": WRONG_PASSWORD}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Token.objects.exists())


class LogoutTests(APITestCase):
    def test_deletes_the_token(self):
        user = User.objects.create_user(username="alice", password=USER_PASSWORD)
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.post(LOGOUT)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Token.objects.exists())
        self.assertEqual(self.client.get(ME).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_requires_authentication(self):
        self.assertEqual(self.client.post(LOGOUT).status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutEverywhereTests(APITestCase):
    def test_also_ends_the_users_shop_api_sessions(self):
        user = make_user(is_staff=True)
        other = make_user()
        token = Token.objects.create(user=user)
        cms_browser, other_browser = Client(), Client()
        cms_browser.force_login(user)  # recorded as a LoginSession by the user_logged_in signal
        other_browser.force_login(other)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.post(LOGOUT)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Session.objects.filter(session_key=cms_browser.session.session_key).exists())
        self.assertTrue(Session.objects.filter(session_key=other_browser.session.session_key).exists())


class HandoffTests(APITestCase):
    def mint(self, user, state=STATE):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return self.client.post(HANDOFF, {"state": state}, format="json")

    @override_settings(SSO_CODE_TTL_SECONDS=45)
    def test_staff_and_superusers_get_a_cms_code_for_their_state(self):
        staff = make_user(is_staff=True)
        superuser = User.objects.create_user(username="root", password=USER_PASSWORD, is_superuser=True)
        for user in (staff, superuser):
            with self.subTest(user.username):
                response = self.mint(user)

                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertEqual(response.data["expires_in"], 45)
                self.assertEqual(redeem_code(response.data["code"], CMS, STATE), user)

    def test_customer_is_forbidden(self):
        response = self.mint(make_user())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(HandoffCode.objects.exists())

    def test_requires_a_token(self):
        response = self.client.post(HANDOFF, {"state": STATE}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_state_is_required_and_capped(self):
        staff = make_user(is_staff=True)
        for label, state in {"blank": "", "too long": "s" * 129}.items():
            with self.subTest(label):
                response = self.mint(staff, state)

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("state", response.data)
        self.assertFalse(HandoffCode.objects.exists())


@override_settings(SSO_CLIENT_SECRET=CLIENT_SECRET)
class HandoffRedeemTests(APITestCase):
    def setUp(self):
        cache.clear()  # the throttle's history lives in the cache and would carry over between tests
        self.staff = make_user(is_staff=True)
        self.code = mint_code(self.staff, STOREFRONT, STATE)

    def redeem(self, *, code=None, state=STATE, secret=CLIENT_SECRET, **headers):
        if secret is not None:
            headers["HTTP_X_SSO_CLIENT_SECRET"] = secret
        return self.client.post(REDEEM, {"code": code or self.code, "state": state}, format="json", **headers)

    def test_returns_the_login_shape_for_the_codes_user(self):
        response = self.redeem()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["token"], Token.objects.get(user=self.staff).key)
        self.assertEqual(response.data["user"]["username"], self.staff.username)

    def test_ignores_a_token_sent_with_the_request(self):
        customer = make_user()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=customer).key}")

        response = self.redeem()

        self.assertEqual(response.data["user"]["username"], self.staff.username)

    def test_bad_secret_is_forbidden_and_leaves_the_code_unspent(self):
        for label, secret in {"missing": None, "wrong": "not-the-secret", "non-ascii": "sécret"}.items():
            with self.subTest(label):
                response = self.redeem(secret=secret)

                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertNotIn("token", response.data)
        self.assertEqual(self.redeem().status_code, status.HTTP_200_OK)

    @override_settings(SSO_CLIENT_SECRET="")
    def test_an_unset_secret_lets_nobody_in(self):
        self.assertEqual(self.redeem(secret="").status_code, status.HTTP_403_FORBIDDEN)

    def test_replay_is_rejected(self):
        self.redeem()

        response = self.redeem()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"detail": INVALID_HANDOFF})

    def test_wrong_state_is_rejected_and_spends_the_code(self):
        response = self.redeem(state="someone-elses-state")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"detail": INVALID_HANDOFF})
        self.assertEqual(self.redeem().data, {"detail": INVALID_HANDOFF})

    def test_cms_code_is_rejected(self):
        code = mint_code(self.staff, CMS, STATE)

        self.assertEqual(self.redeem(code=code).data, {"detail": INVALID_HANDOFF})

    def test_oversized_state_is_rejected_before_redeeming(self):
        response = self.redeem(state="s" * 129)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("state", response.data)
        self.assertIsNone(HandoffCode.objects.get().used_at)

    def test_is_throttled(self):
        allowed, _ = ScopedRateThrottle().parse_rate(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["sso"])
        for _ in range(allowed):
            self.redeem(secret="not-the-secret")

        self.assertEqual(self.redeem().status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_spoofed_forwarded_for_does_not_reset_the_throttle(self):
        allowed, _ = ScopedRateThrottle().parse_rate(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["sso"])
        for n in range(allowed):
            self.redeem(secret="not-the-secret", HTTP_X_FORWARDED_FOR=f"198.51.100.{n}")

        response = self.redeem(HTTP_X_FORWARDED_FOR="203.0.113.1")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class MeTests(APITestCase):
    def test_returns_the_current_user(self):
        user = User.objects.create_user(username="alice", email="a@example.com", is_staff=True)
        self.client.force_authenticate(user)

        response = self.client.get(ME)

        self.assertEqual(response.data, {"id": user.pk, "username": "alice", "email": "a@example.com", "is_staff": True})

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(ME).status_code, status.HTTP_401_UNAUTHORIZED)
