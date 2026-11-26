"""The shop user's login lives in the session as an API token plus a cached user record.

There is no Django auth in this project. Sessions are signed cookies, so shop-api,
which checks the token on every call, is where a login is really ended.
"""
from __future__ import annotations

from django.contrib.sessions.backends.base import SessionBase

from .cart import CART_KEY

TOKEN_KEY = "shop_token"
USER_KEY = "shop_user"


def sign_in(session: SessionBase, token: str, user: dict) -> None:
    # With signed cookies cycle_key only marks the session for saving: there is no
    # server-side id to rotate. The cookie is a signature of the contents, so storing
    # the token already gives the browser a new value nobody held before.
    session.cycle_key()
    session[TOKEN_KEY] = token
    session[USER_KEY] = user


def sign_out(session: SessionBase) -> None:
    # The cart goes with the login, so the next person at this browser starts empty.
    # Other session keys are left alone.
    session.pop(TOKEN_KEY, None)
    session.pop(USER_KEY, None)
    session.pop(CART_KEY, None)
    session.cycle_key()


def current_token(session: SessionBase) -> str | None:
    return session.get(TOKEN_KEY)


def current_user(session: SessionBase) -> dict | None:
    return session.get(USER_KEY)
