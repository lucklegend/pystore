from storefront.api import ApiError

from .helpers import StorefrontTestCase, address

LIST_URL = "/account/addresses/"


def form_data(**overrides) -> dict:
    return {"label": "home", "custom_label": "", "recipient_name": "Alice Cruz", "phone": "+63 912 345 6789",
            "line1": "12 Rizal Street", "line2": "", "city": "Quezon City", "region": "", "postcode": "1100",
            "country": "PH", **overrides}


class LoginRequiredTests(StorefrontTestCase):
    URLS = (LIST_URL, f"{LIST_URL}new/", f"{LIST_URL}4/edit/", f"{LIST_URL}4/delete/")

    def test_anonymous_users_are_sent_to_login(self):
        for url in self.URLS:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/account/login/?next="))
        self.api.list_addresses.assert_not_called()
        self.api.get_address.assert_not_called()


class AddressListTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.log_in()

    def test_badge_on_the_default_and_set_default_only_on_the_others(self):
        self.api.list_addresses.return_value = [
            address(1, is_default=True, label_display="Home"),
            address(2, label="office", label_display="Office"),
        ]

        response = self.client.get(LIST_URL)

        self.assertContains(response, 'class="badge">Default</span>', count=1)
        self.assertContains(response, "Set as default</button>", count=1)
        self.assertContains(response, 'action="/account/addresses/2/default/"')
        self.assertNotContains(response, 'action="/account/addresses/1/default/"')
        self.assertContains(response, "+ New address")

    def test_empty_list_invites_the_first_address(self):
        response = self.client.get(LIST_URL)

        self.assertContains(response, "You haven't saved a delivery address yet.")
        self.assertContains(response, "Add an address")

    def test_the_cap_hides_new_address_and_shows_the_cap_line(self):
        self.api.list_addresses.return_value = [address(pk) for pk in range(1, 21)]

        response = self.client.get(LIST_URL)

        self.assertNotContains(response, "+ New address")
        self.assertContains(response, "You've saved 20 addresses, the most allowed. Delete one to add another.")


class CreateAddressTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.log_in()

    def test_new_form_prefills_from_the_saved_addresses(self):
        self.api.list_addresses.return_value = [address(1, is_default=True, recipient_name="Mom", country="SG")]

        response = self.client.get(f"{LIST_URL}new/")

        self.assertEqual(response.context["form"].initial, {"recipient_name": "Mom", "country": "SG", "is_default": False})
        self.assertContains(response, "New address")

    def test_posts_the_payload_and_flashes_plain_save(self):
        self.api.create_address.return_value = address(9, label_display="Home", is_default=False)

        response = self.client.post(f"{LIST_URL}new/", form_data())

        self.api.create_address.assert_called_once_with({
            "label": "home", "custom_label": "", "is_default": False, "recipient_name": "Alice Cruz",
            "phone": "+63 912 345 6789", "line1": "12 Rizal Street", "line2": "", "city": "Quezon City",
            "region": "", "postcode": "1100", "country": "PH",
        })
        self.assertRedirects(response, LIST_URL, fetch_redirect_response=False)
        self.assertEqual(self.messages(response), ["Saved Home address."])

    def test_flashes_the_default_when_the_new_address_is_the_default(self):
        self.api.create_address.return_value = address(9, label_display="Home", is_default=True)

        response = self.client.post(f"{LIST_URL}new/", form_data())

        self.assertEqual(self.messages(response), ["Saved Home address as your default."])

    def test_invalid_form_does_not_call_the_api_and_focuses_the_first_error(self):
        response = self.client.post(f"{LIST_URL}new/", form_data(city="", country=""))

        self.assertEqual(response.status_code, 200)
        self.api.create_address.assert_not_called()
        self.assertContains(response, 'autofocus')
        self.assertEqual(response.content.decode().count("autofocus"), 1)
        self.assertTrue(response.context["form"].fields["city"].widget.attrs["autofocus"])

    def test_api_validation_errors_land_on_the_form(self):
        self.api.create_address.side_effect = ApiError(
            400, {"phone": ["Enter a valid phone number."], "detail": "You can save up to 20 addresses."}
        )

        response = self.client.post(f"{LIST_URL}new/", form_data())

        form = response.context["form"]
        self.assertEqual(form.errors["phone"], ["Enter a valid phone number."])
        self.assertEqual(form.non_field_errors(), ["You can save up to 20 addresses."])
        self.assertEqual(response.status_code, 200)


class EditAddressTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.log_in()

    def test_prefills_including_other_with_a_name(self):
        self.api.get_address.return_value = address(
            4, label="other", custom_label="Mom's house", label_display="Mom's house"
        )

        response = self.client.get(f"{LIST_URL}4/edit/")

        initial = response.context["form"].initial
        self.assertEqual(initial["label"], "other")
        self.assertEqual(initial["custom_label"], "Mom's house")
        self.assertContains(response, "Edit Mom&#x27;s house address")
        self.assertContains(response, 'value="Mom&#x27;s house"')
        self.assertRegex(response.content.decode(), r'<input[^>]*value="other"[^>]*checked')

    def test_put_updates_and_flashes_plain_save(self):
        self.api.get_address.return_value = address(4)
        self.api.update_address.return_value = address(4, label_display="Home")

        response = self.client.post(f"{LIST_URL}4/edit/", form_data())

        self.assertEqual(self.api.update_address.call_args.args[0], 4)
        self.api.create_address.assert_not_called()
        self.assertRedirects(response, LIST_URL, fetch_redirect_response=False)
        self.assertEqual(self.messages(response), ["Saved Home address."])

    def test_flash_when_becoming_the_default(self):
        self.api.get_address.return_value = address(4, is_default=False)
        self.api.update_address.return_value = address(4, is_default=True)

        response = self.client.post(f"{LIST_URL}4/edit/", form_data(is_default="on"))

        self.assertEqual(self.messages(response), ["Saved Home address as your default."])

    def test_flash_when_unsetting_the_default(self):
        self.api.get_address.return_value = address(4, is_default=True)
        self.api.update_address.return_value = address(4, is_default=False)

        response = self.client.post(f"{LIST_URL}4/edit/", form_data())

        self.assertEqual(self.messages(response), ["Saved Home address. You don't have a default address now."])

    def test_flash_when_staying_the_default_is_plain(self):
        self.api.get_address.return_value = address(4, is_default=True)
        self.api.update_address.return_value = address(4, is_default=True)

        response = self.client.post(f"{LIST_URL}4/edit/", form_data(is_default="on"))

        self.assertEqual(self.messages(response), ["Saved Home address."])

    def test_an_api_404_becomes_a_404_page(self):
        self.api.get_address.side_effect = ApiError(404, {"detail": "Not found."})

        self.assertEqual(self.client.get(f"{LIST_URL}4/edit/").status_code, 404)
        self.assertEqual(self.client.get(f"{LIST_URL}4/delete/").status_code, 404)


class SetDefaultTests(StorefrontTestCase):
    def test_needs_post(self):
        self.log_in()

        response = self.client.get(f"{LIST_URL}4/default/")

        self.assertEqual(response.status_code, 405)
        self.api.set_default_address.assert_not_called()

    def test_sets_the_default_and_flashes(self):
        self.log_in()
        self.api.set_default_address.return_value = address(4, label="office", label_display="Office", is_default=True)

        response = self.client.post(f"{LIST_URL}4/default/")

        self.api.set_default_address.assert_called_once_with(4)
        self.assertRedirects(response, LIST_URL, fetch_redirect_response=False)
        self.assertEqual(self.messages(response), ["Office is now your default address."])

    def test_logged_out_goes_to_login_with_the_list_as_next(self):
        response = self.client.post(f"{LIST_URL}4/default/")

        self.assertRedirects(
            response, "/account/login/?next=%2Faccount%2Faddresses%2F", fetch_redirect_response=False
        )
        self.api.set_default_address.assert_not_called()


class DeleteAddressTests(StorefrontTestCase):
    def setUp(self):
        super().setUp()
        self.log_in()

    def test_get_asks_for_confirmation_and_warns_about_the_default(self):
        self.api.get_address.return_value = address(4, is_default=True)

        response = self.client.get(f"{LIST_URL}4/delete/")

        self.assertContains(response, "Delete this address?")
        self.assertContains(response, "This is your default address.")
        self.api.delete_address.assert_not_called()

    def test_no_default_warning_for_other_addresses(self):
        self.api.get_address.return_value = address(4)

        response = self.client.get(f"{LIST_URL}4/delete/")

        self.assertNotContains(response, "This is your default address.")

    def test_deleting_a_plain_address(self):
        self.api.get_address.return_value = address(4)

        response = self.client.post(f"{LIST_URL}4/delete/")

        self.api.delete_address.assert_called_once_with(4)
        self.assertRedirects(response, LIST_URL, fetch_redirect_response=False)
        self.assertEqual(self.messages(response), ["Deleted Home address."])

    def test_deleting_the_default_says_there_is_none_now(self):
        self.api.get_address.return_value = address(4, is_default=True)

        response = self.client.post(f"{LIST_URL}4/delete/")

        self.assertEqual(
            self.messages(response),
            ["Deleted Home address. You don't have a default address now. "
             "Use Set as default on another address to choose one."],
        )
