from django.apps import AppConfig
from django.conf import settings


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:
        from django.contrib.auth.signals import user_logged_in, user_logged_out
        from django.db.models.signals import post_save

        from . import signals

        user_logged_in.connect(signals.record_login_session, dispatch_uid="accounts.record_login_session")
        user_logged_out.connect(signals.forget_login_session, dispatch_uid="accounts.forget_login_session")
        post_save.connect(
            signals.sync_moderators, sender=settings.AUTH_USER_MODEL, dispatch_uid="accounts.sync_moderators"
        )
