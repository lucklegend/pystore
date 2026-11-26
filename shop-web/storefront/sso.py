"""Session side of single sign-on with the CMS on shop-api.

When the storefront starts a handoff, it keeps one random `state` and the `next`
URL in the session. The callback must bring the same `state` back, which ties the
code it carries to this browser and blocks login CSRF and code injection.
"""
from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlsplit

from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest
from django.utils.http import url_has_allowed_host_and_scheme

PENDING_KEY = "sso_pending"


def begin(session: SessionBase, next_url: str) -> str:
    state = secrets.token_urlsafe(32)
    session[PENDING_KEY] = {"state": state, "next": next_url}
    return state


def take_state(session: SessionBase, state: str) -> str | None:
    """Return the stored `next` when `state` matches. The stored state is used up either way."""
    pending = session.pop(PENDING_KEY, None)
    if pending is None or not state:
        return None
    # Compare bytes: compare_digest rejects non-ASCII str, and `state` comes from the query string.
    if not hmac.compare_digest(pending["state"].encode(), state.encode()):
        return None
    return pending["next"]


def allowed_next(request: HttpRequest, target: str, default: str, cms_url: str) -> str:
    """`target` if it stays on this host or on the CMS host (`cms_url`'s host and port), else `default`."""
    allowed_hosts = {request.get_host(), urlsplit(cms_url).netloc}
    if url_has_allowed_host_and_scheme(target, allowed_hosts=allowed_hosts, require_https=request.is_secure()):
        return target
    return default
