from config.fixture_secrets import USER_PASSWORD, WRONG_PASSWORD
from storefront.api import ApiError
from storefront.session import TOKEN_KEY, USER_KEY

from .helpers import CUSTOMER, StorefrontTestCase

LOGIN = "/account/login/"
REGISTER = "/account/register/"
LOGOUT = "/account/logout/"


class LoginViewTests(StorefrontTestCase):
    def test_shows_the_form_and_keeps_next(self):
        response = self.client.get(LOGIN, {"next": "/shop/cart/"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="next" value="/shop/cart/"')

    def test_logged_in_users_are_sent_to_the_shop(self):
        self.log_in()

        response = self.client.get(LOGIN)

        self.assertRedirects(response, "/shop/", fetch_redirect_response=False)

    def test_success_signs_in_and_follows_next(self):
        self.api.login.return_value = {"token": "tok", "user": CUSTOMER}

        response = self.client.post(LOGIN, {"username": "alice", "password": USER_PASSWORD, "next": "/shop/cart/"})

        self.api.login.assert_called_once_with("alice", USER_PASSWORD)
        self.assertRedirects(response, "/shop/cart/", fetch_redirect_response=False)
        self.assertEqual(self.client.session[TOKEN_KEY], "tok")
        self.assertEqual(self.client.session[USER_KEY], CUSTOMER)
        self.assertIn("Welcome back, alice!", self.messages(response))

    def test_ignores_an_off_site_next(self):
        self.api.login.return_value = {"token": "tok", "user": CUSTOMER}

        for target in ("https://evil.example/", "//evil.example/"):
            with self.subTest(target=target):
                self.client.session.flush()
                response = self.client.post(LOGIN, {"username": "alice", "password": USER_PASSWORD, "next": target})

                self.assertRedirects(response, "/shop/", fetch_redirect_response=False)

    def test_bad_credentials_show_a_form_error(self):
        self.api.login.side_effect = ApiError(400, {"non_field_errors": ["Unable to log in."]})

        response = self.client.post(LOGIN, {"username": "alice", "password": WRONG_PASSWORD})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].non_field_errors(), ["Wrong username or password."])
        self.assertNotIn(TOKEN_KEY, self.client.session)

    def test_api_outage_is_not_reported_as_bad_credentials(self):
        self.api.login.side_effect = ApiError(503, {"detail": "The shop service is unavailable."})

        response = self.client.post(LOGIN, {"username": "alice", "password": USER_PASSWORD})

        self.assertEqual(response.status_code, 503)
        self.assertTemplateUsed(response, "storefront/api_error.html")

    def test_incomplete_form_does_not_call_the_api(self):
        response = self.client.post(LOGIN, {"username": "alice"})

        self.assertEqual(response.status_code, 200)
        self.api.login.assert_not_called()


class RegisterViewTests(StorefrontTestCase):
    def data(self, **overrides) -> dict:
        return {"username": "alice", "email": "alice@example.com", "password": USER_PASSWORD,
                "password_confirm": USER_PASSWORD, **overrides}

    def test_success_signs_in(self):
        self.api.register.return_value = {"token": "tok", "user": CUSTOMER}

        response = self.client.post(REGISTER, self.data())

        self.api.register.assert_called_once_with("alice", "alice@example.com", USER_PASSWORD)
        self.assertRedirects(response, "/shop/", fetch_redirect_response=False)
        self.assertEqual(self.client.session[USER_KEY], CUSTOMER)

    def test_api_validation_errors_land_on_the_form(self):
        self.api.register.side_effect = ApiError(
            400, {"email": ["An account with this email already exists."], "password": ["Too common."]}
        )

        response = self.client.post(REGISTER, self.data())

        form = response.context["form"]
        self.assertEqual(form.errors["email"], ["An account with this email already exists."])
        self.assertEqual(form.errors["password"], ["Too common."])

    def test_mismatched_passwords_do_not_call_the_api(self):
        self.client.post(REGISTER, self.data(password_confirm=WRONG_PASSWORD))

        self.api.register.assert_not_called()

    def test_logged_in_users_are_sent_to_the_shop(self):
        self.log_in()

        self.assertRedirects(self.client.get(REGISTER), "/shop/", fetch_redirect_response=False)


class LogoutViewTests(StorefrontTestCase):
    def test_requires_post(self):
        self.assertEqual(self.client.get(LOGOUT).status_code, 405)

    def test_revokes_token_and_clears_session(self):
        self.log_in()

        response = self.client.post(LOGOUT)

        self.api.logout.assert_called_once_with()
        self.assertRedirects(response, "/shop/", fetch_redirect_response=False)
        self.assertNotIn(TOKEN_KEY, self.client.session)
        self.assertIn("You have been logged out.", self.messages(response))

    def test_logs_out_locally_even_if_the_api_fails(self):
        self.log_in()
        self.api.logout.side_effect = ApiError(503, None)

        response = self.client.post(LOGOUT)

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(USER_KEY, self.client.session)

    def test_anonymous_logout_skips_the_api(self):
        self.client.post(LOGOUT)

        self.api.logout.assert_not_called()
