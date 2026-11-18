"""The shop customer's login lives in the session as an API token plus a cached user record.

This is separate from Django auth, which this project uses only for Wagtail CMS editors.
"""
from __future__ import annotations

from django.contrib.sessions.backends.base import SessionBase

TOKEN_KEY = "shop_token"
USER_KEY = "shop_user"


def sign_in(session: SessionBase, token: str, user: dict) -> None:
    session.cycle_key()  # new session id on login, against session fixation
    session[TOKEN_KEY] = token
    session[USER_KEY] = user


def sign_out(session: SessionBase) -> None:
    # Pop only shop keys so a CMS editor logged in on the same browser stays logged in.
    session.pop(TOKEN_KEY, None)
    session.pop(USER_KEY, None)
    session.cycle_key()


def current_token(session: SessionBase) -> str | None:
    return session.get(TOKEN_KEY)


def current_user(session: SessionBase) -> dict | None:
    return session.get(USER_KEY)
