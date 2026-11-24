"""Keeps everyone except active staff and superusers out of the CMS."""
import re
from typing import Callable

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

# CMS routes anyone may reach, relative to CMS_URL_PREFIX: signing in and out, the SSO
# hand-off and Wagtail's password reset. Matched whole, so `login/../pages/` is not exempt.
EXEMPT_ROUTES = re.compile(
    r"(?:login|logout|sso/authorize|sso/callback"
    r"|password_reset(?:/done|/complete|/confirm/[^/]+/[^/]+)?)/"
)


def has_cms_access(user_pk: int) -> bool:
    """Read the user from the database, so a revoked flag counts even when the change skipped signals."""
    return (
        get_user_model()
        .objects.filter(Q(is_staff=True) | Q(is_superuser=True), pk=user_pk, is_active=True)
        .exists()
    )


class CmsStaffOnlyMiddleware:
    """Sign out a non-staff user on any CMS request and send them to the CMS login page."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.prefix = settings.CMS_URL_PREFIX

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        if self.is_gated(request.path_info) and user.is_authenticated and not has_cms_access(user.pk):
            logout(request)
            messages.error(request, "Only staff can use the CMS. Sign in with a staff account.")
            return redirect(f"{self.prefix}login/")
        return self.get_response(request)

    def is_gated(self, path: str) -> bool:
        if not path.startswith(self.prefix):
            return False
        return not EXEMPT_ROUTES.fullmatch(path.removeprefix(self.prefix))
