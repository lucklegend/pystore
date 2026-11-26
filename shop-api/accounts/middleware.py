"""Keeps all but active staff and superusers out of the CMS; ends any session signed out elsewhere."""
import re
from typing import Callable

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.models import AbstractUser
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from .cms_views import SILENT_TRIED_KEY
from .services import SESSION_EPOCH_KEY, is_cms_eligible

# CMS routes anyone may reach, relative to CMS_URL_PREFIX: signing in and out, the SSO
# hand-off and Wagtail's password reset. Matched whole, so `login/../pages/` is not exempt.
EXEMPT_ROUTES = re.compile(
    r"(?:login|logout|sso/authorize|sso/callback"
    r"|password_reset(?:/done|/complete|/confirm/[^/]+/[^/]+)?)/"
)

NO_LONGER_ALLOWED = "Your account no longer has access to the CMS."


def fresh_user(user_pk: int) -> AbstractUser | None:
    """Read the user from the database, so a revoked flag counts even when the change skipped signals.

    The same query brings their sign-out epoch along as `current_sign_out_epoch`.
    """
    return (
        get_user_model()
        .objects.annotate(current_sign_out_epoch=Coalesce("sign_out_epoch__value", 0))
        .filter(pk=user_pk)
        .first()
    )


def signed_out_since_login(request: HttpRequest, user: AbstractUser) -> bool:
    """True once the user signed out everywhere after this session signed in, even if its key rotated since."""
    return request.session.get(SESSION_EPOCH_KEY) != user.current_sign_out_epoch


class CmsStaffOnlyMiddleware:
    """End, on every request, a session whose user signed out everywhere since it signed in.

    Outside the CMS (the admin, wagtaildocs' /documents/, anything else that reads the session) and on
    exempt CMS routes, the view then runs for the signed-out visitor, so the admin and private document
    collections send them to their own login pages. On the rest of the CMS, a user who may no longer
    use it is also signed out, and either kind is sent to the CMS login page.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.prefix = settings.CMS_URL_PREFIX

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.get_response(request)
        user = fresh_user(request.user.pk)
        path = request.path_info
        gated = path.startswith(self.prefix) and not EXEMPT_ROUTES.fullmatch(path.removeprefix(self.prefix))
        if not gated:
            # Exempt CMS routes are checked too: sso/authorize would otherwise mint a storefront
            # code for a revoked session.
            if user is None or signed_out_since_login(request, user):
                logout(request)
            return self.get_response(request)
        if user is None or not is_cms_eligible(user):
            logout(request)
            # The login page would otherwise try a silent sign-in, be refused, and add a second message.
            request.session[SILENT_TRIED_KEY] = True
            messages.error(request, NO_LONGER_ALLOWED)
            return redirect(f"{self.prefix}login/")
        if signed_out_since_login(request, user):
            # No message: the login page's silent attempt finds no storefront session and shows the form.
            logout(request)
            return redirect(f"{self.prefix}login/")
        return self.get_response(request)
