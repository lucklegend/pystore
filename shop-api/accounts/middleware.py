"""Keeps all but active staff and superusers out of the CMS; ends CMS and admin sessions signed out elsewhere."""
import re
from typing import Callable

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.views import redirect_to_login
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

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
    """Sign out, on any CMS request, a user who may no longer use the CMS or who signed out everywhere since.

    Exempt CMS routes get the sign-out-everywhere check only, and then run for the signed-out visitor.
    Django admin requests get the sign-out-everywhere check only; the admin enforces is_staff itself.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.prefix = settings.CMS_URL_PREFIX

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path_info
        if not (path.startswith(self.prefix) and request.user.is_authenticated):
            return self.get_response(request)
        user = fresh_user(request.user.pk)
        if EXEMPT_ROUTES.fullmatch(path.removeprefix(self.prefix)):
            # Still checked: sso/authorize would otherwise mint a storefront code for a revoked session.
            # Signed out here, the view answers as for any anonymous visitor.
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

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., HttpResponse],
        view_args: tuple[object, ...],
        view_kwargs: dict[str, object],
    ) -> HttpResponse | None:
        """For any view in the admin site's namespace, including its catch-all 404, end a session signed out since."""
        match = request.resolver_match
        if match is None or match.namespace != admin.site.name or not request.user.is_authenticated:
            return None
        user = fresh_user(request.user.pk)
        if user is not None and not signed_out_since_login(request, user):
            return None
        logout(request)
        return redirect_to_login(request.get_full_path(), reverse(f"{admin.site.name}:login"))
