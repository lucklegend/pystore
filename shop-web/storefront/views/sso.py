"""Single sign-on with the CMS on shop-api.

- begin and callback: the storefront is the consumer. A CMS password login sends the
  browser here, and the code from shop-api becomes a storefront session.
- authorize: the storefront is the issuer. The CMS asks who is logged in here, and gets
  a code minted with this session's token.
- logout: the CMS has already signed the user out everywhere. This only finishes that
  here, and only once shop-api confirms the token is dead.

Each view handles ApiError itself, so the middleware's 401 branch never sends the
browser to the storefront login page in the middle of a handoff.
"""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from ..api import ApiError, ShopApi
from ..session import current_token, sign_in, sign_out
from ..sso import allowed_next, begin, take_state

HOME = "/"
AUTHORIZE_ERRORS = {401: "login_required", 403: "access_denied"}


@require_GET
def sso_begin(request: HttpRequest) -> HttpResponse:
    next_url = allowed_next(request, request.GET.get("next", ""), HOME, settings.SHOP_API_PUBLIC_URL)
    state = begin(request.session, next_url)
    return redirect(f"{settings.SHOP_API_PUBLIC_URL}/cms/sso/authorize/?{urlencode({'state': state})}")


@require_GET
def sso_callback(request: HttpRequest) -> HttpResponse:
    state = request.GET.get("state", "")
    next_url = take_state(request.session, state)
    if next_url is None:
        messages.info(request, "That sign-in link has expired. Please log in again.")
        response = redirect(HOME)
    else:
        code = request.GET.get("code")
        if code:
            # A client without the session's token: redeeming must not act as whoever is logged in now.
            api = ShopApi(settings.SHOP_API_URL, timeout=settings.SHOP_API_TIMEOUT)
            try:
                result = api.redeem_handoff(code, state, settings.SSO_CLIENT_SECRET)
            except ApiError:
                pass  # The CMS sign-in already worked; the storefront just stays as it was.
            else:
                sign_in(request.session, result["token"], result["user"])
        response = redirect(next_url)
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def sso_authorize(request: HttpRequest) -> HttpResponse:
    state = request.GET.get("state", "")
    query = {"error": "login_required", "state": state}
    if current_token(request.session):
        try:
            handoff = request.shop_api.create_handoff(state)
        except ApiError as error:
            if error.status == 401:
                sign_out(request.session)
            query["error"] = AUTHORIZE_ERRORS.get(error.status, "temporarily_unavailable")
        else:
            query = {"code": handoff["code"], "state": state}
    # The callback URL is fixed here and never read from the request, so a code only ever goes to shop-api.
    response = redirect(f"{settings.SHOP_API_PUBLIC_URL}/cms/sso/callback/?{urlencode(query)}")
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def sso_logout(request: HttpRequest) -> HttpResponse:
    if current_token(request.session):
        try:
            request.shop_api.me()
        except ApiError as error:
            # Only a dead token ends the session, so a forged link to this URL cannot log anyone out.
            if error.status == 401:
                sign_out(request.session)
    return redirect(allowed_next(request, request.GET.get("next", ""), HOME, settings.SHOP_API_PUBLIC_URL))
