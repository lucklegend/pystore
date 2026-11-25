"""Single sign-on between the storefront and the CMS: one-time codes, and logging out everywhere."""
import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.authtoken.models import Token

from .models import HandoffCode, LoginSession, SignOutEpoch

# The user's SignOutEpoch as it stood when this session signed in. CmsStaffOnlyMiddleware signs out a stale one.
SESSION_EPOCH_KEY = "accounts_sign_out_epoch"


def is_cms_eligible(user: AbstractUser) -> bool:
    """The rule CmsStaffOnlyMiddleware enforces: active, and staff or superuser."""
    return user.is_active and (user.is_staff or user.is_superuser)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def mint_code(
    user: AbstractUser,
    audience: HandoffCode.Audience,
    state: str,
    *,
    now: Callable[[], datetime] = timezone.now,
    ttl: int | None = None,
) -> str:
    """Issue a code for `user` that the `audience` side can redeem once, with the same `state`, within `ttl` seconds.

    `ttl` defaults to SSO_CODE_TTL_SECONDS. Raises PermissionDenied for an inactive user, and for a
    CMS code when the user may not use the CMS.
    """
    if not user.is_active or (audience == HandoffCode.Audience.CMS and not is_cms_eligible(user)):
        raise PermissionDenied
    current = now()
    lifetime = settings.SSO_CODE_TTL_SECONDS if ttl is None else ttl
    code = secrets.token_urlsafe(32)
    HandoffCode.objects.filter(expires_at__lte=current).delete()
    HandoffCode.objects.create(
        code_hash=sha256(code),
        user=user,
        audience=audience,
        state_hash=sha256(state),
        expires_at=current + timedelta(seconds=lifetime),
    )
    return code


def redeem_code(
    code: str,
    audience: HandoffCode.Audience,
    state: str,
    *,
    now: Callable[[], datetime] = timezone.now,
) -> AbstractUser | None:
    """Return the user a valid code was issued to, or None. Any presented code is spent, even a misused one.

    The conditional UPDATE is the single-use guarantee: of two concurrent redeems only one sees a row count of 1.
    """
    current = now()
    code_hash = sha256(code)
    with transaction.atomic():
        claimed = HandoffCode.objects.filter(
            code_hash=code_hash, used_at__isnull=True, expires_at__gt=current
        ).update(used_at=current)
        if claimed != 1:
            return None
        handoff = HandoffCode.objects.select_related("user").get(code_hash=code_hash)
    if handoff.audience != audience or not hmac.compare_digest(handoff.state_hash, sha256(state)):
        return None
    user = handoff.user
    if not user.is_active or (audience == HandoffCode.Audience.CMS and not is_cms_eligible(user)):
        return None
    return user


def sign_out_epoch(user: AbstractUser) -> int:
    return SignOutEpoch.objects.filter(user=user).values_list("value", flat=True).first() or 0


def sign_out_everywhere(user: AbstractUser) -> None:
    """End the user's API token and every shop-api session they signed in with.

    Bumping the epoch ends every CMS session, including one whose key rotated since login.
    Deleting the recorded sessions also ends the ones outside the CMS whose key never rotated.
    """
    with transaction.atomic():
        Token.objects.filter(user=user).delete()
        SignOutEpoch.objects.get_or_create(user=user)
        SignOutEpoch.objects.filter(user=user).update(value=F("value") + 1)
        login_sessions = LoginSession.objects.filter(user=user)
        Session.objects.filter(session_key__in=login_sessions.values("session_key")).delete()
        login_sessions.delete()
