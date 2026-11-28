from django.test import TestCase
from rest_framework.exceptions import NotFound, ValidationError

from store.addresses import MAX_ADDRESSES_PER_USER, create_address, delete_address, update_address
from store.models import DeliveryAddress

from .factories import make_address, make_user


def address_data(**overrides) -> dict:
    """A payload as the serializer's validated_data would hand it over."""
    fields = {
        "label": DeliveryAddress.Label.HOME,
        "custom_label": "",
        "recipient_name": "Juan dela Cruz",
        "phone": "+63 912 345 6789",
        "line1": "12 Mabini Street",
        "city": "Makati",
        "country": "PH",
    }
    return fields | overrides


def default_ids(user) -> list[int]:
    return list(user.delivery_addresses.filter(is_default=True).values_list("pk", flat=True))


class CreateAddressTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_saves_the_address_for_the_user(self):
        address = create_address(self.user, address_data(city="Cebu"))

        address.refresh_from_db()
        self.assertEqual(address.user, self.user)
        self.assertEqual(address.city, "Cebu")

    def test_ignores_a_user_in_the_payload(self):
        other = make_user()

        address = create_address(self.user, address_data(user=other))

        self.assertEqual(address.user, self.user)
        self.assertFalse(other.delivery_addresses.exists())

    def test_first_address_becomes_the_default_even_when_the_payload_says_false(self):
        address = create_address(self.user, address_data(is_default=False))

        self.assertEqual(default_ids(self.user), [address.pk])

    def test_first_address_becomes_the_default_when_the_payload_leaves_it_out(self):
        address = create_address(self.user, address_data())

        self.assertEqual(default_ids(self.user), [address.pk])

    def test_later_address_is_not_the_default_unless_asked(self):
        first = create_address(self.user, address_data())

        create_address(self.user, address_data(is_default=False))

        self.assertEqual(default_ids(self.user), [first.pk])

    def test_later_address_with_is_default_moves_the_default(self):
        first = create_address(self.user, address_data())

        second = create_address(self.user, address_data(is_default=True))

        self.assertEqual(default_ids(self.user), [second.pk])
        first.refresh_from_db()
        self.assertFalse(first.is_default)

    def test_rejects_the_address_past_the_cap_and_creates_nothing(self):
        for _ in range(MAX_ADDRESSES_PER_USER):
            make_address(self.user)

        with self.assertRaises(ValidationError) as caught:
            create_address(self.user, address_data(is_default=True))

        self.assertEqual(caught.exception.detail, {"detail": "You can save up to 20 addresses."})
        self.assertEqual(self.user.delivery_addresses.count(), MAX_ADDRESSES_PER_USER)

    def test_rejected_default_past_the_cap_keeps_the_old_default(self):
        old_default = make_address(self.user, is_default=True)
        for _ in range(MAX_ADDRESSES_PER_USER - 1):
            make_address(self.user)

        with self.assertRaises(ValidationError):
            create_address(self.user, address_data(is_default=True))

        self.assertEqual(default_ids(self.user), [old_default.pk])

    def test_the_cap_counts_only_the_users_own_addresses(self):
        other = make_user()
        for _ in range(MAX_ADDRESSES_PER_USER):
            make_address(other)

        create_address(self.user, address_data())

        self.assertEqual(self.user.delivery_addresses.count(), 1)


class UpdateAddressTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.default = make_address(self.user, is_default=True)
        self.other = make_address(self.user)

    def test_applies_the_changes(self):
        update_address(self.other, {"city": "Cebu", "label": DeliveryAddress.Label.OFFICE})

        self.other.refresh_from_db()
        self.assertEqual(self.other.city, "Cebu")
        self.assertEqual(self.other.label, DeliveryAddress.Label.OFFICE)

    def test_setting_is_default_moves_the_default(self):
        update_address(self.other, {"is_default": True})

        self.assertEqual(default_ids(self.user), [self.other.pk])

    def test_setting_is_default_on_the_default_keeps_it(self):
        update_address(self.default, {"is_default": True, "city": "Cebu"})

        self.assertEqual(default_ids(self.user), [self.default.pk])

    def test_editing_the_default_without_is_default_keeps_it(self):
        update_address(self.default, {"city": "Cebu"})

        self.assertEqual(default_ids(self.user), [self.default.pk])

    def test_turning_the_default_off_leaves_none(self):
        update_address(self.default, {"is_default": False})

        self.assertEqual(default_ids(self.user), [])
        self.assertEqual(self.user.delivery_addresses.count(), 2)

    def test_applies_the_changes_to_the_row_as_it_is_now(self):
        stale = DeliveryAddress.objects.get(pk=self.other.pk)
        DeliveryAddress.objects.filter(pk=self.other.pk).update(city="Davao")

        saved = update_address(stale, {"phone": "+63 917 000 0000"})

        self.other.refresh_from_db()
        self.assertEqual((self.other.city, self.other.phone), ("Davao", "+63 917 000 0000"))
        self.assertEqual((saved.city, saved.phone), ("Davao", "+63 917 000 0000"))

    def test_an_address_deleted_meanwhile_is_not_saved_again(self):
        DeliveryAddress.objects.filter(pk=self.other.pk).delete()

        with self.assertRaises(NotFound):
            update_address(self.other, {"is_default": True})

        self.assertFalse(DeliveryAddress.objects.filter(pk=self.other.pk).exists())
        self.assertEqual(default_ids(self.user), [self.default.pk])


class DeleteAddressTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_deleting_the_default_leaves_none_and_keeps_the_others(self):
        default = make_address(self.user, is_default=True)
        others = [make_address(self.user, city="Cebu"), make_address(self.user, city="Davao")]

        delete_address(default)

        self.assertFalse(DeliveryAddress.objects.filter(pk=default.pk).exists())
        self.assertEqual(default_ids(self.user), [])
        self.assertEqual(
            sorted(self.user.delivery_addresses.values_list("pk", "city", "is_default")),
            sorted((address.pk, address.city, False) for address in others),
        )

    def test_deleting_another_address_keeps_the_default(self):
        default = make_address(self.user, is_default=True)
        other = make_address(self.user)

        delete_address(other)

        self.assertEqual(default_ids(self.user), [default.pk])


class WritableFieldsTests(TestCase):
    """Keys outside the address fields never reach the row, whoever calls the service."""

    def setUp(self):
        self.user = make_user()
        self.victim = make_user()
        self.victims_address = make_address(self.victim, is_default=True, city="Davao")

    def assert_victim_untouched(self):
        self.victims_address.refresh_from_db()
        self.assertEqual(
            (self.victims_address.user, self.victims_address.city, self.victims_address.is_default),
            (self.victim, "Davao", True),
        )
        self.assertEqual(self.victim.delivery_addresses.count(), 1)

    def test_create_ignores_owner_and_row_keys(self):
        victim_id, row_id = self.victim.pk, self.victims_address.pk

        address = create_address(
            self.user, address_data(user=self.victim, user_id=victim_id, id=row_id, pk=row_id, is_default=True)
        )

        address.refresh_from_db()
        self.assertEqual(address.user, self.user)
        self.assertNotEqual(address.pk, row_id)
        self.assert_victim_untouched()

    def test_update_ignores_owner_and_row_keys(self):
        own = make_address(self.user, is_default=True)
        victim_id, row_id = self.victim.pk, self.victims_address.pk

        saved = update_address(
            own, {"user": self.victim, "user_id": victim_id, "id": row_id, "pk": row_id, "city": "Cebu"}
        )

        own.refresh_from_db()
        self.assertEqual((saved.pk, own.user, own.city, own.is_default), (own.pk, self.user, "Cebu", True))
        self.assert_victim_untouched()


class OtherUsersDefaultTests(TestCase):
    """No operation on one user's addresses may touch another user's default."""

    def setUp(self):
        self.user = make_user()
        self.neighbour = make_user()
        self.neighbours_default = make_address(self.neighbour, is_default=True)

    def assert_neighbour_untouched(self):
        self.assertEqual(default_ids(self.neighbour), [self.neighbours_default.pk])

    def test_first_address_leaves_it(self):
        create_address(self.user, address_data())

        self.assert_neighbour_untouched()

    def test_new_default_leaves_it(self):
        make_address(self.user, is_default=True)

        create_address(self.user, address_data(is_default=True))

        self.assert_neighbour_untouched()

    def test_moving_the_default_leaves_it(self):
        make_address(self.user, is_default=True)
        other = make_address(self.user)

        update_address(other, {"is_default": True})

        self.assert_neighbour_untouched()

    def test_turning_the_default_off_leaves_it(self):
        default = make_address(self.user, is_default=True)

        update_address(default, {"is_default": False})

        self.assert_neighbour_untouched()

    def test_deleting_the_default_leaves_it(self):
        default = make_address(self.user, is_default=True)

        delete_address(default)

        self.assert_neighbour_untouched()
