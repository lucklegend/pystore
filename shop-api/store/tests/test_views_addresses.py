import unicodedata
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from store.addresses import MAX_ADDRESSES_PER_USER
from store.models import DeliveryAddress

from .factories import make_address, make_user

ADDRESSES = "/api/addresses/"
COUNTRIES = "/api/countries/"
PHONE_MESSAGE = "Enter a valid phone number, for example +63 912 345 6789."


def address_url(address_id: int) -> str:
    return f"{ADDRESSES}{address_id}/"


def payload(**overrides) -> dict:
    """A full address body, as shop-web's form sends it."""
    fields = {
        "label": "home",
        "custom_label": "",
        "is_default": False,
        "recipient_name": "Ana Reyes",
        "phone": "+63 912 345 6789",
        "line1": "1 Rizal Avenue",
        "line2": "",
        "city": "Cebu",
        "region": "",
        "postcode": "6000",
        "country": "PH",
    }
    return fields | overrides


def row(address: DeliveryAddress) -> tuple:
    """The stored values a request must not change."""
    address.refresh_from_db()
    return (address.user_id, address.label, address.custom_label, address.is_default, address.city, address.country)


def default_ids(user) -> list[int]:
    return list(user.delivery_addresses.filter(is_default=True).values_list("pk", flat=True))


class CountryListTests(APITestCase):
    def test_anyone_gets_the_whole_list_unpaginated(self):
        response = self.client.get(COUNTRIES)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertIn({"code": "PH", "name": "Philippines"}, response.data)
        self.assertIn({"code": "SG", "name": "Singapore"}, response.data)

    def test_countries_are_sorted_by_name(self):
        names = [country["name"] for country in self.client.get(COUNTRIES).data]

        # Accents are ignored, so Åland Islands sorts among the A's.
        def ascii_name(name: str) -> str:
            return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()

        self.assertEqual(names, sorted(names, key=ascii_name))
        self.assertEqual(names[0], "Afghanistan")


class AddressAccessTests(APITestCase):
    def setUp(self):
        cache.clear()  # the write throttle's history lives in the cache and would carry over between tests
        self.user = make_user()
        self.neighbour = make_user()
        self.neighbours_address = make_address(self.neighbour, is_default=True, city="Davao")

    def test_anonymous_callers_get_401_and_change_nothing(self):
        url = address_url(self.neighbours_address.pk)
        before = row(self.neighbours_address)

        responses = [
            self.client.get(ADDRESSES),
            self.client.post(ADDRESSES, payload(), format="json"),
            self.client.get(url),
            self.client.put(url, payload(), format="json"),
            self.client.patch(url, {"city": "Cebu"}, format="json"),
            self.client.delete(url),
        ]

        self.assertEqual([response.status_code for response in responses], [status.HTTP_401_UNAUTHORIZED] * 6)
        self.assertEqual(row(self.neighbours_address), before)
        self.assertEqual(DeliveryAddress.objects.count(), 1)

    def test_lists_only_your_own_addresses_default_first(self):
        older = make_address(self.user)
        default = make_address(self.user, is_default=True)
        newer = make_address(self.user)
        now = timezone.now()
        for address, age in ((older, 3), (default, 2), (newer, 1)):
            DeliveryAddress.objects.filter(pk=address.pk).update(updated_at=now - timedelta(days=age))
        self.client.force_authenticate(self.user)

        response = self.client.get(ADDRESSES)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([address["id"] for address in response.data], [default.pk, newer.pk, older.pk])

    def test_another_users_address_is_404_on_every_verb_and_unchanged(self):
        url = address_url(self.neighbours_address.pk)
        before = row(self.neighbours_address)
        self.client.force_authenticate(self.user)

        responses = {
            "GET": self.client.get(url),
            "PUT": self.client.put(url, payload(city="Cebu", is_default=False), format="json"),
            "PATCH": self.client.patch(url, {"city": "Cebu", "is_default": False}, format="json"),
            "DELETE": self.client.delete(url),
        }

        for verb, response in responses.items():
            with self.subTest(verb):
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(row(self.neighbours_address), before)

    def test_staff_see_and_reach_only_their_own_addresses(self):
        staff = make_user(is_staff=True)
        own = make_address(staff)
        self.client.force_authenticate(staff)

        listing = self.client.get(ADDRESSES)
        foreign = self.client.get(address_url(self.neighbours_address.pk))

        self.assertEqual([address["id"] for address in listing.data], [own.pk])
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)


class CreateAddressApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # the write throttle's history lives in the cache and would carry over between tests
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def post(self, body: dict):
        return self.client.post(ADDRESSES, body, format="json")

    def test_creates_the_address_for_the_caller_in_the_contract_shape(self):
        response = self.post(payload())

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        address = DeliveryAddress.objects.get()
        self.assertEqual(address.user, self.user)
        self.assertEqual(
            set(response.data),
            set(payload()) | {"id", "label_display", "country_display", "created_at", "updated_at"},
        )
        self.assertEqual(response.data["id"], address.pk)
        self.assertEqual(response.data["label_display"], "Home")
        self.assertEqual(response.data["country"], "PH")
        self.assertEqual(response.data["country_display"], "Philippines")
        # The first address is the default, whatever the payload says.
        self.assertTrue(response.data["is_default"])

    def test_ignores_owner_and_row_keys_in_the_payload(self):
        victim = make_user()
        victims_address = make_address(victim, is_default=True, city="Davao")
        before = row(victims_address)

        response = self.post(payload(user=victim.pk, user_id=victim.pk, id=victims_address.pk))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data["id"], victims_address.pk)
        self.assertEqual(DeliveryAddress.objects.get(pk=response.data["id"]).user, self.user)
        self.assertEqual(row(victims_address), before)
        self.assertEqual(victim.delivery_addresses.count(), 1)

    def test_reports_each_missing_required_field(self):
        response = self.post({})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"recipient_name", "phone", "line1", "city", "country"})
        self.assertEqual(response.data["city"], ["This field is required."])
        self.assertFalse(DeliveryAddress.objects.exists())

    def test_rejects_a_country_outside_the_list(self):
        for country in ("ZZ", ""):
            with self.subTest(country=country):
                response = self.post(payload(country=country))

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("country", response.data)
        self.assertFalse(DeliveryAddress.objects.exists())

    def test_rejects_a_label_outside_the_choices(self):
        response = self.post(payload(label="work"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("label", response.data)

    def test_rejects_a_bad_phone_with_the_example_message(self):
        response = self.post(payload(phone="call me"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["phone"], [PHONE_MESSAGE])

    def test_other_without_a_name_shows_as_other(self):
        response = self.post(payload(label="other", custom_label=""))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["label_display"], "Other")

    def test_other_with_a_name_shows_the_name_trimmed(self):
        response = self.post(payload(label="other", custom_label="  Mom's house "))

        self.assertEqual(response.data["custom_label"], "Mom's house")
        self.assertEqual(response.data["label_display"], "Mom's house")

    def test_a_name_on_home_is_dropped(self):
        response = self.post(payload(label="home", custom_label="Mom's house"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["custom_label"], "")
        self.assertEqual(DeliveryAddress.objects.get().custom_label, "")

    def test_rejects_a_name_over_50_characters(self):
        response = self.post(payload(label="other", custom_label="x" * 51))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("custom_label", response.data)

    def test_rejects_the_address_past_the_cap(self):
        for _ in range(MAX_ADDRESSES_PER_USER):
            make_address(self.user)

        response = self.post(payload())

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"detail": "You can save up to 20 addresses."})
        self.assertEqual(self.user.delivery_addresses.count(), MAX_ADDRESSES_PER_USER)


class UpdateAddressApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # the write throttle's history lives in the cache and would carry over between tests
        self.user = make_user()
        self.default = make_address(self.user, is_default=True)
        self.other = make_address(self.user, label=DeliveryAddress.Label.OTHER, custom_label="Lola's")
        self.client.force_authenticate(self.user)

    def test_patch_is_default_moves_the_default(self):
        response = self.client.patch(address_url(self.other.pk), {"is_default": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_default"])
        self.assertEqual(default_ids(self.user), [self.other.pk])

    def test_put_replaces_the_address(self):
        body = payload(city="Davao", is_default=True)

        response = self.client.put(address_url(self.default.pk), body, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["city"], "Davao")
        self.default.refresh_from_db()
        self.assertEqual(self.default.city, "Davao")

    def test_put_and_patch_ignore_owner_and_row_keys(self):
        victim = make_user()
        victims_address = make_address(victim, is_default=True, city="Davao")
        before = row(victims_address)
        keys = {"user": victim.pk, "user_id": victim.pk, "id": victims_address.pk}

        put = self.client.put(address_url(self.default.pk), payload(city="Iloilo", **keys), format="json")
        patch = self.client.patch(address_url(self.default.pk), {"city": "Baguio", **keys}, format="json")

        self.assertEqual([put.status_code, patch.status_code], [status.HTTP_200_OK] * 2)
        self.assertEqual([put.data["id"], patch.data["id"]], [self.default.pk] * 2)
        self.default.refresh_from_db()
        self.assertEqual((self.default.user, self.default.city), (self.user, "Baguio"))
        self.assertEqual(row(victims_address), before)

    def test_patching_other_to_home_drops_its_name(self):
        response = self.client.patch(address_url(self.other.pk), {"label": "home"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual((response.data["custom_label"], response.data["label_display"]), ("", "Home"))

    def test_patching_a_name_keeps_the_saved_label(self):
        renamed = self.client.patch(address_url(self.other.pk), {"custom_label": "Tita's"}, format="json")
        on_home = self.client.patch(address_url(self.default.pk), {"custom_label": "Tita's"}, format="json")

        self.assertEqual(renamed.data["label_display"], "Tita's")
        self.assertEqual((on_home.data["custom_label"], on_home.data["label_display"]), ("", "Home"))


class DeleteAddressApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # the write throttle's history lives in the cache and would carry over between tests
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def test_deleting_the_default_leaves_no_default(self):
        default = make_address(self.user, is_default=True)
        other = make_address(self.user)

        response = self.client.delete(address_url(default.pk))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(list(self.user.delivery_addresses.values_list("pk", flat=True)), [other.pk])
        self.assertEqual(default_ids(self.user), [])


class AddressThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()  # the write throttle's history lives in the cache and would carry over between tests
        self.user = make_user()
        self.address = make_address(self.user)
        self.client.force_authenticate(self.user)

    def allowed_per_window(self) -> int:
        allowed, _ = ScopedRateThrottle().parse_rate(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["addresses"])
        return allowed

    def patch(self):
        return self.client.patch(address_url(self.address.pk), {"city": "Cebu"}, format="json")

    def test_writes_are_throttled_per_user_and_reads_are_not(self):
        for _ in range(self.allowed_per_window()):
            self.patch()

        throttled = self.patch()
        listing = self.client.get(ADDRESSES)
        self.client.force_authenticate(make_user())
        someone_else = self.client.post(ADDRESSES, payload(), format="json")

        self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(someone_else.status_code, status.HTTP_201_CREATED)
