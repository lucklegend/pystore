"""Signal handlers, connected in AccountsConfig.ready()."""
from django.contrib.auth.models import AbstractUser, Group
from django.http import HttpRequest

from .models import LoginSession
from .services import SESSION_EPOCH_KEY, sign_out_epoch

# Wagtail's default group: CMS access plus add, change, publish and lock on pages.
MODERATORS_GROUP = "Moderators"


def record_login_session(sender, request: HttpRequest, user: AbstractUser, **kwargs) -> None:
    """Remember the session a user signed in with, so sign_out_everywhere can end it."""
    request.session[SESSION_EPOCH_KEY] = sign_out_epoch(user)
    # Signing in again inside the same session keeps its key, so the row may already exist.
    LoginSession.objects.update_or_create(session_key=request.session.session_key, defaults={"user": user})


def forget_login_session(sender, request: HttpRequest, user: AbstractUser | None, **kwargs) -> None:
    LoginSession.objects.filter(session_key=request.session.session_key).delete()


def sync_moderators(sender, instance: AbstractUser, raw: bool, **kwargs) -> None:
    """Staff who are not superusers moderate in the CMS; anyone who loses staff stops. Other groups are left alone."""
    if raw:  # loaddata: the user's groups arrive with the fixture
        return
    group = Group.objects.filter(name=MODERATORS_GROUP).first()
    if group is None:
        return
    if instance.is_staff and not instance.is_superuser:
        instance.groups.add(group)
    elif not instance.is_staff:
        instance.groups.remove(group)
