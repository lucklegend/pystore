"""The delivery address book. Writes go to shop-api, which scopes every address to the token's user."""
from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..api import ApiError
from ..countries import country_choices
from ..decorators import shop_login_required
from ..forms import MAX_ADDRESSES, AddressForm, address_initial, apply_api_errors, new_address_initial

NO_DEFAULT_NOTE = "You don't have a default address now."


def focus_first_error(form: AddressForm) -> None:
    """Autofocus the first field with an error. The label radios are left out, since the attribute would land on all three."""
    for name in form.errors:
        if name in form.fields and name != "label":
            form.fields[name].widget.attrs["autofocus"] = True
            return


def saved_message(label: str, was_default: bool, is_default: bool) -> str:
    if is_default and not was_default:
        return f"Saved {label} address as your default."
    if was_default and not is_default:
        return f"Saved {label} address. {NO_DEFAULT_NOTE}"
    return f"Saved {label} address."


@shop_login_required
def address_list(request: HttpRequest) -> HttpResponse:
    addresses = request.shop_api.list_addresses()
    context = {"addresses": addresses, "can_add": len(addresses) < MAX_ADDRESSES, "max_addresses": MAX_ADDRESSES}
    return render(request, "storefront/addresses/address_list.html", context)


def save_address(request: HttpRequest, address: dict | None, initial: dict) -> HttpResponse:
    """Shared create/edit flow: address is None for create."""
    countries = country_choices(request.public_api)
    form = AddressForm(request.POST or None, initial=initial, countries=countries)

    if request.method == "POST" and form.is_valid():
        try:
            if address:
                saved = request.shop_api.update_address(address["id"], form.to_payload())
            else:
                saved = request.shop_api.create_address(form.to_payload())
        except ApiError as error:
            if error.status != 400:
                raise
            apply_api_errors(form, error)
        else:
            was_default = bool(address and address["is_default"])
            messages.success(request, saved_message(saved["label_display"], was_default, saved["is_default"]))
            return redirect("storefront:address_list")

    focus_first_error(form)
    return render(request, "storefront/addresses/address_form.html", {"form": form, "address": address})


@shop_login_required
def address_create(request: HttpRequest) -> HttpResponse:
    initial = new_address_initial(request.shop_api.list_addresses(), request.shop_user.get("full_name", ""))
    return save_address(request, None, initial)


@shop_login_required
def address_edit(request: HttpRequest, address_id: int) -> HttpResponse:
    address = request.shop_api.get_address(address_id)
    return save_address(request, address, address_initial(address))


@shop_login_required
def address_delete(request: HttpRequest, address_id: int) -> HttpResponse:
    address = request.shop_api.get_address(address_id)
    if request.method == "POST":
        request.shop_api.delete_address(address_id)
        message = f"Deleted {address['label_display']} address."
        if address["is_default"]:
            message += f" {NO_DEFAULT_NOTE} Use Set as default on another address to choose one."
        messages.success(request, message)
        return redirect("storefront:address_list")
    return render(request, "storefront/addresses/address_confirm_delete.html", {"address": address})


@require_POST
def address_set_default(request: HttpRequest, address_id: int) -> HttpResponse:
    if not request.shop_user:
        # This view is POST-only, so send them back to the list after login, not here.
        messages.info(request, "Please log in to continue.")
        query = urlencode({"next": reverse("storefront:address_list")})
        return redirect(f"{reverse('storefront:login')}?{query}")
    saved = request.shop_api.set_default_address(address_id)
    messages.success(request, f"{saved['label_display']} is now your default address.")
    return redirect("storefront:address_list")
