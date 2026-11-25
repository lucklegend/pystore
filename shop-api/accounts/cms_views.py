"""Single sign-on in the browser for the CMS, around Wagtail's own login and logout views.

- login: an anonymous visit first asks the storefront, once per session, whether a staff
  user is signed in there (shop-api is the consumer). After a password sign-in the browser
  goes on to the storefront, so the same user is signed in there too.
- authorize: shop-api is the issuer. The storefront asks who is signed in to the CMS.
- callback: a code from the storefront becomes a CMS session.
- logout: signs the user out everywhere, then lets the storefront finish its side.
"""
import hmac
import secrets
from urllib.parse import urlencode, urljoin, urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from wagtail.admin.views.account import LoginView, LogoutView, get_user_login_form

from .models import HandoffCode
from .services import is_cms_eligible, mint_code, redeem_code, sign_out_everywhere

PENDING_KEY = "cms_sso_pending"
# Set once a silent sign-in has been tried in this session, so the login page shows the form instead of looping.
SILENT_TRIED_KEY = "cms_sso_silent_tried"
# token_urlsafe(32) is 43 characters; anything far longer is not a state either side issued.
MAX_STATE_LENGTH = 128

NO_ACCESS = "Your account doesn't have access to the CMS."
CALLBACK_ERRORS = {
    "login_required": None,  # simply not signed in on the storefront: the plain form, no message
    "access_denied": (messages.ERROR, NO_ACCESS),
    "temporarily_unavailable": (messages.WARNING, "We couldn't sign you in from the storefront. Sign in below."),
}
EXPIRED = (messages.WARNING, "Your sign-in link has expired. Sign in below.")

wagtail_login = LoginView.as_view()
wagtail_logout = LogoutView.as_view()


def cms_login_url() -> str:
    return f"{settings.CMS_URL_PREFIX}login/"


def allowed_next(request: HttpRequest, target: str, default: str) -> str:
    """`target` if it stays on this host or on the storefront host (host and port), else `default`."""
    allowed_hosts = {request.get_host(), urlsplit(settings.STOREFRONT_URL).netloc}
    if url_has_allowed_host_and_scheme(target, allowed_hosts=allowed_hosts, require_https=request.is_secure()):
        return target
    return default


def begin(session: SessionBase, next_url: str) -> str:
    state = secrets.token_urlsafe(32)
    session[PENDING_KEY] = {"state": state, "next": next_url}
    return state


def take_state(session: SessionBase, state: str) -> str | None:
    """Return the stored `next` when `state` matches. The stored state is used up either way."""
    pending = session.pop(PENDING_KEY, None)
    if pending is None or not state or len(state) > MAX_STATE_LENGTH:
        return None
    # Compare bytes: compare_digest rejects non-ASCII str, and `state` comes from the query string.
    if not hmac.compare_digest(pending["state"].encode(), state.encode()):
        return None
    return pending["next"]


def cms_login(request: HttpRequest) -> HttpResponse:
    if request.method == "GET" and not request.user.is_authenticated and not request.session.get(SILENT_TRIED_KEY):
        request.session[SILENT_TRIED_KEY] = True
        state = begin(request.session, allowed_next(request, request.GET.get("next", ""), settings.CMS_URL_PREFIX))
        return redirect(f"{settings.STOREFRONT_URL}/account/sso/authorize/?{urlencode({'state': state})}")

    response = wagtail_login(request)
    if request.method != "POST" or response.status_code != 302 or not request.user.is_authenticated:
        return response
    if not is_cms_eligible(request.user):
        # A customer's password is right, but the CMS is not theirs: undo the sign-in and say so on the form.
        logout(request)
        return refuse_sign_in(request)
    # Wagtail has already chosen and checked where to go; the storefront signs in too, then sends the browser there.
    cms_next = urljoin(f"{settings.SHOP_API_PUBLIC_URL}{request.path}", response["Location"])
    response["Location"] = f"{settings.STOREFRONT_URL}/account/sso/begin/?{urlencode({'next': cms_next})}"
    return response


def refuse_sign_in(request: HttpRequest) -> HttpResponse:
    """Wagtail's sign-in form again, username kept, with the refusal as its non-field error."""
    form = get_user_login_form()(request, data=request.POST)
    form.is_valid()  # add_error needs cleaned data
    form.add_error(None, NO_ACCESS)
    view = LoginView()
    view.setup(request)
    return view.render_to_response(view.get_context_data(form=form))


@require_POST  # a GET must not reach Wagtail's view: it clears the cookie and queues a "logged out" message
def cms_logout(request: HttpRequest) -> HttpResponse:
    user = request.user
    # Resolve the lazy user now: after Wagtail's logout it would read the flushed session as anonymous.
    if not user.is_authenticated:
        return wagtail_logout(request)
    response = wagtail_logout(request)
    if request.user.is_authenticated:  # Wagtail refused, for example a failed CSRF check
        return response
    sign_out_everywhere(user)
    # Coming back to the login page should show the form, not try a pointless silent sign-in.
    request.session[SILENT_TRIED_KEY] = True
    login_url = f"{settings.SHOP_API_PUBLIC_URL}{cms_login_url()}"
    return redirect(f"{settings.STOREFRONT_URL}/account/sso/logout/?{urlencode({'next': login_url})}")


@require_GET
def sso_authorize(request: HttpRequest) -> HttpResponse:
    state = request.GET.get("state", "")
    if not state or len(state) > MAX_STATE_LENGTH:
        return HttpResponseBadRequest()
    query = {"error": "login_required", "state": state}
    if request.user.is_authenticated:
        if is_cms_eligible(request.user):
            query = {"code": mint_code(request.user, HandoffCode.Audience.STOREFRONT, state), "state": state}
        else:
            query["error"] = "access_denied"
    # The callback URL is fixed here and never read from the request, so a code only ever goes to the storefront.
    response = redirect(f"{settings.STOREFRONT_URL}/account/sso/callback/?{urlencode(query)}")
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def sso_callback(request: HttpRequest) -> HttpResponse:
    state = request.GET.get("state", "")
    code = request.GET.get("code", "")
    next_url = take_state(request.session, state)
    # Redeem before acting on the state check: a presented code is spent even when the state is wrong.
    user = redeem_code(code, HandoffCode.Audience.CMS, state) if code else None
    if next_url is not None and user is not None:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        response = redirect(next_url)
    else:
        request.session[SILENT_TRIED_KEY] = True
        error = request.GET.get("error", "") if next_url is not None else ""
        notice = CALLBACK_ERRORS.get(error, EXPIRED)
        if notice is not None:
            messages.add_message(request, *notice)
        login_url = cms_login_url()
        response = redirect(f"{login_url}?{urlencode({'next': next_url})}" if next_url else login_url)
    response["Referrer-Policy"] = "no-referrer"
    return response
