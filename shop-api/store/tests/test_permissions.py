from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase

from store.permissions import IsStaffOrReadOnly


def request(method: str, user) -> SimpleNamespace:
    return SimpleNamespace(method=method, user=user)


class IsStaffOrReadOnlyTests(SimpleTestCase):
    def setUp(self):
        self.permission = IsStaffOrReadOnly()
        self.staff = SimpleNamespace(is_staff=True)
        self.customer = SimpleNamespace(is_staff=False)

    def test_anyone_may_read(self):
        for method in ("GET", "HEAD", "OPTIONS"):
            for user in (AnonymousUser(), self.customer, None):
                with self.subTest(method=method, user=user):
                    self.assertTrue(self.permission.has_permission(request(method, user), view=None))

    def test_only_staff_may_write(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assertTrue(self.permission.has_permission(request(method, self.staff), view=None))
                self.assertFalse(self.permission.has_permission(request(method, self.customer), view=None))
                self.assertFalse(self.permission.has_permission(request(method, AnonymousUser()), view=None))
                self.assertFalse(self.permission.has_permission(request(method, None), view=None))
