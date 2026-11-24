from datetime import UTC, datetime, timedelta
from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from accounts.models import HandoffCode, LoginSession
from accounts.services import is_cms_eligible, mint_code, redeem_code, sha256, sign_out_everywhere
from config.fixture_secrets import USER_PASSWORD
from store.tests.factories import make_user

User = get_user_model()

CMS = HandoffCode.Audience.CMS
STOREFRONT = HandoffCode.Audience.STOREFRONT
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
STATE = "state-from-the-consumer"


def at(moment: datetime):
    return lambda: moment


def make_superuser(username: str, *, is_staff: bool = True):
    """Created in one save, so the post_save handler only ever sees the finished superuser."""
    return User.objects.create_user(
        username=username, password=USER_PASSWORD, is_staff=is_staff, is_superuser=True
    )


class IsCmsEligibleTests(TestCase):
    def test_active_staff_and_superusers_only(self):
        customer = make_user()
        inactive_staff = make_user(is_staff=True)
        inactive_staff.is_active = False
        cases = {
            "staff": (make_user(is_staff=True), True),
            "superuser without the staff flag": (make_superuser("root", is_staff=False), True),
            "customer": (customer, False),
            "inactive staff": (inactive_staff, False),
        }
        for label, (user, expected) in cases.items():
            with self.subTest(label):
                self.assertIs(is_cms_eligible(user), expected)


class MintCodeTests(TestCase):
    def setUp(self):
        self.staff = make_user(is_staff=True)

    def test_stores_only_hashes_of_the_code_and_state(self):
        code = mint_code(self.staff, CMS, STATE, now=at(NOW), ttl=60)

        handoff = HandoffCode.objects.get()
        self.assertEqual(handoff.code_hash, sha256(code))
        self.assertEqual(handoff.state_hash, sha256(STATE))
        stored = [str(value) for value in HandoffCode.objects.values_list().get()]
        self.assertNotIn(code, stored)
        self.assertNotIn(STATE, stored)
        self.assertEqual(handoff.expires_at, NOW + timedelta(seconds=60))
        self.assertIsNone(handoff.used_at)

    @override_settings(SSO_CODE_TTL_SECONDS=17)
    def test_ttl_defaults_to_the_setting(self):
        mint_code(self.staff, CMS, STATE, now=at(NOW))

        self.assertEqual(HandoffCode.objects.get().expires_at, NOW + timedelta(seconds=17))

    def test_codes_are_unique(self):
        first = mint_code(self.staff, CMS, STATE, now=at(NOW), ttl=60)
        second = mint_code(self.staff, CMS, STATE, now=at(NOW), ttl=60)

        self.assertNotEqual(first, second)

    def test_purges_expired_codes(self):
        mint_code(self.staff, CMS, STATE, now=at(NOW), ttl=60)
        fresh = mint_code(self.staff, CMS, STATE, now=at(NOW + timedelta(seconds=30)), ttl=60)

        mint_code(self.staff, CMS, STATE, now=at(NOW + timedelta(seconds=60)), ttl=60)

        self.assertEqual(HandoffCode.objects.count(), 2)
        self.assertTrue(HandoffCode.objects.filter(code_hash=sha256(fresh)).exists())

    def test_refuses_a_cms_code_to_a_customer(self):
        with self.assertRaises(PermissionDenied):
            mint_code(make_user(), CMS, STATE, now=at(NOW), ttl=60)

        self.assertFalse(HandoffCode.objects.exists())

    def test_storefront_code_is_open_to_any_active_user(self):
        mint_code(make_user(), STOREFRONT, STATE, now=at(NOW), ttl=60)

        self.assertEqual(HandoffCode.objects.count(), 1)

    def test_refuses_an_inactive_user(self):
        self.staff.is_active = False
        for audience in (CMS, STOREFRONT):
            with self.subTest(audience), self.assertRaises(PermissionDenied):
                mint_code(self.staff, audience, STATE, now=at(NOW), ttl=60)


class RedeemCodeTests(TestCase):
    def setUp(self):
        self.staff = make_user(is_staff=True)
        self.code = mint_code(self.staff, CMS, STATE, now=at(NOW), ttl=60)

    def redeem(self, *, code=None, audience=CMS, state=STATE, moment=NOW + timedelta(seconds=1)):
        return redeem_code(code or self.code, audience, state, now=at(moment))

    def test_returns_the_user_and_marks_the_code_used(self):
        moment = NOW + timedelta(seconds=5)

        self.assertEqual(self.redeem(moment=moment), self.staff)
        self.assertEqual(HandoffCode.objects.get().used_at, moment)

    def test_storefront_code_redeems_for_a_customer(self):
        customer = make_user()
        code = mint_code(customer, STOREFRONT, STATE, now=at(NOW), ttl=60)

        self.assertEqual(self.redeem(code=code, audience=STOREFRONT), customer)

    def test_second_redeem_of_the_same_code_is_rejected(self):
        # Two redeems racing for one code: the conditional UPDATE claims the row for exactly one.
        results = [self.redeem(), self.redeem()]

        self.assertEqual(results, [self.staff, None])

    def test_expired_code_is_rejected(self):
        self.assertIsNone(self.redeem(moment=NOW + timedelta(seconds=60)))
        self.assertIsNone(HandoffCode.objects.get().used_at)

    def test_unknown_code_is_rejected(self):
        self.assertIsNone(self.redeem(code="not-a-code"))

    def test_wrong_audience_is_rejected_and_spends_the_code(self):
        self.assertIsNone(self.redeem(audience=STOREFRONT))
        self.assertIsNone(self.redeem())

    def test_wrong_state_is_rejected_and_spends_the_code(self):
        self.assertIsNone(self.redeem(state="someone-elses-state"))
        self.assertIsNone(self.redeem())

    def test_user_deactivated_since_minting_is_rejected(self):
        User.objects.filter(pk=self.staff.pk).update(is_active=False)

        self.assertIsNone(self.redeem())

    def test_cms_code_of_a_user_demoted_since_minting_is_rejected(self):
        User.objects.filter(pk=self.staff.pk).update(is_staff=False)

        self.assertIsNone(self.redeem())


class SignOutEverywhereTests(TestCase):
    def test_deletes_the_token_and_every_recorded_session(self):
        user = make_user(is_staff=True)
        other = make_user()
        Token.objects.create(user=user)
        Token.objects.create(user=other)
        for signed_in in (user, user, other):
            self.client_class().force_login(signed_in)  # each sends user_logged_in from its own session
        self.assertEqual(LoginSession.objects.filter(user=user).count(), 2)
        other_key = LoginSession.objects.get(user=other).session_key

        sign_out_everywhere(user)

        self.assertFalse(Token.objects.filter(user=user).exists())
        self.assertFalse(LoginSession.objects.filter(user=user).exists())
        self.assertEqual(list(Session.objects.values_list("session_key", flat=True)), [other_key])
        self.assertTrue(Token.objects.filter(user=other).exists())


class LoginSessionSignalTests(TestCase):
    def test_login_records_the_session_and_logout_forgets_it(self):
        user = make_user()
        self.client.force_login(user)
        self.assertEqual(LoginSession.objects.get().session_key, self.client.session.session_key)
        self.assertEqual(LoginSession.objects.get().user, user)

        self.client.logout()

        self.assertFalse(LoginSession.objects.exists())


class ModeratorsSyncTests(TestCase):
    def setUp(self):
        self.moderators = Group.objects.get(name="Moderators")

    def is_moderator(self, user) -> bool:
        return user.groups.filter(pk=self.moderators.pk).exists()

    def test_new_staff_user_joins_moderators(self):
        self.assertTrue(self.is_moderator(make_user(is_staff=True)))
        self.assertFalse(self.is_moderator(make_user()))

    def test_promoted_customer_joins_moderators(self):
        user = make_user()

        user.is_staff = True
        user.save()

        self.assertTrue(self.is_moderator(user))

    def test_demoted_staff_leaves_moderators_but_keeps_other_groups(self):
        editors = Group.objects.get(name="Editors")
        user = make_user(is_staff=True)
        user.groups.add(editors)

        user.is_staff = False
        user.save()

        self.assertFalse(self.is_moderator(user))
        self.assertTrue(user.groups.filter(pk=editors.pk).exists())

    def test_superuser_is_not_added(self):
        user = make_superuser("root")

        self.assertFalse(self.is_moderator(user))

    def test_promotion_to_superuser_keeps_an_existing_membership(self):
        user = make_user(is_staff=True)

        user.is_superuser = True
        user.save()

        self.assertTrue(self.is_moderator(user))


class CmsModeratorsMigrationTests(TestCase):
    def test_adds_existing_non_superuser_staff_only(self):
        migration = import_module("accounts.migrations.0002_cms_moderators")
        staff, superuser, customer = make_user(), make_user(), make_user()
        # Set the flags without save(), as they stood before the post_save handler existed.
        User.objects.filter(pk__in=[staff.pk, superuser.pk]).update(is_staff=True)
        User.objects.filter(pk=superuser.pk).update(is_superuser=True)

        migration.add_staff_to_moderators(apps, schema_editor=None)

        self.assertEqual(list(Group.objects.get(name="Moderators").user_set.all()), [staff])

    def test_does_nothing_without_the_group(self):
        migration = import_module("accounts.migrations.0002_cms_moderators")
        Group.objects.filter(name="Moderators").delete()
        User.objects.filter(pk=make_user().pk).update(is_staff=True)

        migration.add_staff_to_moderators(apps, schema_editor=None)

        self.assertFalse(Group.objects.filter(name="Moderators").exists())
