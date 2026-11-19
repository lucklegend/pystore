import secrets

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from config.fixture_secrets import USER_PASSWORD, WRONG_PASSWORD

User = get_user_model()

REGISTER = "/api/auth/register/"
LOGIN = "/api/auth/login/"
LOGOUT = "/api/auth/logout/"
ME = "/api/auth/me/"


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


class MeTests(APITestCase):
    def test_returns_the_current_user(self):
        user = User.objects.create_user(username="alice", email="a@example.com", is_staff=True)
        self.client.force_authenticate(user)

        response = self.client.get(ME)

        self.assertEqual(response.data, {"id": user.pk, "username": "alice", "email": "a@example.com", "is_staff": True})

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(ME).status_code, status.HTTP_401_UNAUTHORIZED)
