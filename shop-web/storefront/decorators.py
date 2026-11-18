"""Access checks for storefront views.

These only shape the UI; shop-api enforces the real permissions on every call.
"""
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def shop_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.shop_user:
            messages.info(request, "Please log in to continue.")
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('storefront:login')}?{query}")
        return view(request, *args, **kwargs)

    return wrapper


def shop_staff_required(view):
    @shop_login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.shop_user.get("is_staff"):
            raise PermissionDenied("Staff only.")
        return view(request, *args, **kwargs)

    return wrapper
