from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..api import ApiError
from ..forms import LoginForm, RegisterForm, apply_api_errors
from ..session import sign_in, sign_out


def safe_next_url(request: HttpRequest, default: str = "storefront:product_list") -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


def login_view(request: HttpRequest) -> HttpResponse:
    if request.shop_user:
        return redirect("storefront:product_list")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            result = request.shop_api.login(form.cleaned_data["username"], form.cleaned_data["password"])
        except ApiError as error:
            if error.status != 400:
                raise
            form.add_error(None, "Wrong username or password.")
        else:
            sign_in(request.session, result["token"], result["user"])
            messages.success(request, f"Welcome back, {result['user']['username']}!")
            return redirect(safe_next_url(request))
    return render(request, "storefront/login.html", {"form": form, "next": request.GET.get("next", "")})


def register_view(request: HttpRequest) -> HttpResponse:
    if request.shop_user:
        return redirect("storefront:product_list")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            result = request.shop_api.register(data["username"], data["email"], data["password"])
        except ApiError as error:
            if error.status != 400:
                raise
            apply_api_errors(form, error)
        else:
            sign_in(request.session, result["token"], result["user"])
            messages.success(request, "Your account is ready.")
            return redirect(safe_next_url(request))
    return render(request, "storefront/register.html", {"form": form})


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    if request.shop_user:
        try:
            request.shop_api.logout()
        except ApiError:
            pass  # Token already gone or API down; the local logout below still applies.
    sign_out(request.session)
    messages.info(request, "You have been logged out.")
    return redirect("storefront:product_list")
