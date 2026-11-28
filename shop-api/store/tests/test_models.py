from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from store.models import DeliveryAddress, Order, resolve_label

from .factories import make_address, make_category, make_order, make_product, make_user


class OrderTotalTests(TestCase):
    def test_total_sums_item_subtotals(self):
        user = make_user()
        order = make_order(user, [(make_product(price="2.50"), 3), (make_product(price="10.00"), 1)])

        self.assertEqual(order.total, Decimal("17.50"))

    def test_total_of_empty_order_is_zero(self):
        order = Order.objects.create(user=make_user())

        self.assertEqual(order.total, Decimal("0.00"))

    def test_total_uses_price_copied_at_checkout(self):
        product = make_product(price="5.00")
        order = make_order(make_user(), [(product, 2)])

        product.price = Decimal("99.00")
        product.save()

        self.assertEqual(order.total, Decimal("10.00"))


class OrderItemTests(TestCase):
    def test_subtotal_is_unit_price_times_quantity(self):
        order = make_order(make_user(), [(make_product(price="3.20"), 4)])

        self.assertEqual(order.items.get().subtotal, Decimal("12.80"))


class StrTests(TestCase):
    def test_category_and_product_use_their_name(self):
        self.assertEqual(str(make_category("Tea")), "Tea")
        self.assertEqual(str(make_product("Green tea")), "Green tea")

    def test_order_shows_id_and_status_label(self):
        order = Order.objects.create(user=make_user(), status=Order.Status.SHIPPED)

        self.assertEqual(str(order), f"Order #{order.pk} (Shipped)")


class CategoryDeletionTests(TestCase):
    def test_deleting_a_category_keeps_its_products(self):
        category = make_category()
        product = make_product(category=category)

        category.delete()
        product.refresh_from_db()

        self.assertIsNone(product.category)


class DeliveryAddressPhoneTests(TestCase):
    def test_accepts_common_formats(self):
        user = make_user()
        for phone in ("+63 912 345 6789", "09123456789", "02 8123-4567 (2)"):
            with self.subTest(phone=phone):
                make_address(user, phone=phone).full_clean()

    def test_rejects_other_text_with_the_example_message(self):
        user = make_user()
        for phone in ("call me", "12345", "+", "-63 912 345 6789", "+63 912 345 6789\n"):
            with self.subTest(phone=phone):
                address = DeliveryAddress(
                    user=user, recipient_name="Ana", phone=phone, line1="1 Rizal Ave", city="Cebu", country="PH"
                )
                with self.assertRaises(ValidationError) as caught:
                    address.full_clean()
                self.assertEqual(
                    caught.exception.message_dict["phone"],
                    ["Enter a valid phone number, for example +63 912 345 6789."],
                )


class DeliveryAddressConstraintTests(TestCase):
    def test_a_user_cannot_have_two_defaults(self):
        user = make_user()
        make_address(user, is_default=True)

        with self.assertRaises(IntegrityError), transaction.atomic():
            make_address(user, is_default=True)

    def test_two_users_can_each_have_a_default(self):
        make_address(make_user(), is_default=True)
        make_address(make_user(), is_default=True)

        self.assertEqual(DeliveryAddress.objects.filter(is_default=True).count(), 2)

    def test_a_user_can_have_many_addresses_that_are_not_default(self):
        user = make_user()
        make_address(user, is_default=True)
        make_address(user)
        make_address(user)

        self.assertEqual(user.delivery_addresses.count(), 3)

    def test_home_cannot_carry_a_custom_label(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_address(make_user(), label=DeliveryAddress.Label.HOME, custom_label="Mom's house")

    def test_other_can_have_a_blank_custom_label(self):
        address = make_address(make_user(), label=DeliveryAddress.Label.OTHER, custom_label="")

        self.assertEqual(address.label_display, "Other")

    def test_label_must_be_one_of_the_choices(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_address(make_user(), label="work")


class ResolveLabelTests(TestCase):
    def test_other_with_a_name_uses_the_name(self):
        self.assertEqual(resolve_label("other", "Mom's house"), "Mom's house")

    def test_other_without_a_name_is_other(self):
        self.assertEqual(resolve_label("other", ""), "Other")

    def test_home_and_office_use_the_choice_name(self):
        self.assertEqual(resolve_label("home", ""), "Home")
        self.assertEqual(resolve_label("office", ""), "Office")

    def test_an_unknown_label_shows_as_stored_instead_of_raising(self):
        self.assertEqual(resolve_label("work", ""), "work")
        self.assertEqual(resolve_label("", ""), "")

    def test_address_label_display_resolves_its_own_fields(self):
        address = make_address(make_user(), label=DeliveryAddress.Label.OTHER, custom_label="Lola's")

        self.assertEqual(address.label_display, "Lola's")


class SnapshotTests(TestCase):
    def test_snapshot_fields_copy_the_address_and_the_country_name(self):
        address = make_address(
            make_user(),
            label=DeliveryAddress.Label.OTHER,
            custom_label="Mom's house",
            recipient_name="Maria Santos",
            phone="+65 6123 4567",
            line1="1 Orchard Road",
            line2="#05-01",
            city="Singapore",
            region="Central",
            postcode="238824",
            country="SG",
        )

        self.assertEqual(
            address.snapshot_fields(),
            {
                "shipping_label": "other",
                "shipping_custom_label": "Mom's house",
                "shipping_recipient_name": "Maria Santos",
                "shipping_phone": "+65 6123 4567",
                "shipping_line1": "1 Orchard Road",
                "shipping_line2": "#05-01",
                "shipping_city": "Singapore",
                "shipping_region": "Central",
                "shipping_postcode": "238824",
                "shipping_country": "SG",
                "shipping_country_name": "Singapore",
            },
        )

    def test_order_without_a_snapshot_has_no_shipping_address(self):
        order = Order.objects.create(user=make_user())

        self.assertIsNone(order.shipping_address)

    def test_order_shipping_address_reads_the_snapshot_columns(self):
        user = make_user()
        address = make_address(user, label=DeliveryAddress.Label.OTHER, custom_label="Lola's", country="PH")
        order = Order.objects.create(user=user, **address.snapshot_fields())

        self.assertEqual(
            order.shipping_address,
            {
                "label": "other",
                "custom_label": "Lola's",
                "label_display": "Lola's",
                "recipient_name": "Juan dela Cruz",
                "phone": "+63 912 345 6789",
                "line1": "12 Mabini Street",
                "line2": "",
                "city": "Makati",
                "region": "",
                "postcode": "",
                "country": "PH",
                "country_display": "Philippines",
            },
        )

    def test_order_shipping_address_uses_the_frozen_country_name(self):
        user = make_user()
        address = make_address(user, country="PH")
        order = Order.objects.create(user=user, **(address.snapshot_fields() | {"shipping_country_name": "Old name"}))

        self.assertEqual(order.shipping_address["country_display"], "Old name")
