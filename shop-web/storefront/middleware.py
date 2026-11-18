from __future__ import annotations

from typing import Callable
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from .api import ApiError, ShopApi
from .session import current_token, current_user, sign_out


class ShopApiMiddleware:
    """Attach an API client and the logged-in shop user to every request,
    and turn API failures that views don't handle into sensible responses."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.shop_api = ShopApi(
            settings.SHOP_API_URL,
            token=current_token(request.session),
            timeout=settings.SHOP_API_TIMEOUT,
        )
        request.shop_user = current_user(request.session)
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        if not isinstance(exception, ApiError):
            return None
        if exception.status == 401:
            sign_out(request.session)
            messages.info(request, "Your session has expired. Please log in again.")
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('storefront:login')}?{query}")
        if exception.status == 404:
            raise Http404(exception.message)
        status = exception.status if exception.status in (403, 503) else 502
        return render(request, "storefront/api_error.html", {"error": exception}, status=status)
