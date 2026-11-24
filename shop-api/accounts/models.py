from django.conf import settings
from django.db import models


class HandoffCode(models.Model):
    """A one-time SSO code, stored only as its SHA-256 and bound to the consumer's `state`."""

    class Audience(models.TextChoices):
        CMS = "cms", "CMS"
        STOREFRONT = "storefront", "Storefront"

    code_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="handoff_codes")
    audience = models.CharField(max_length=20, choices=Audience.choices)
    state_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.audience} code for {self.user_id}"


class LoginSession(models.Model):
    """A Django session a user signed in with, so logging out elsewhere can end it."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="login_sessions")
    session_key = models.CharField(max_length=40, unique=True)  # Session.session_key's length
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"session for {self.user_id}"
