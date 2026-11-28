from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.validators import RegexValidator

from .api import ApiError

# A mirror of the API's per-user cap, used only to hide the add entry points early.
# shop-api enforces the limit, and its 400 stays the backstop.
MAX_ADDRESSES = 20


def apply_api_errors(form: forms.Form, error: ApiError) -> None:
    """Show a 400 from the API on the form fields whose names match the API's."""
    for field, messages in error.field_errors().items():
        target = field if field in form.fields else None
        for message in messages:
            form.add_error(target, message)
    for message in error.general_errors():
        form.add_error(None, message)


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "username"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class RegisterForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autocomplete": "username"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password_confirm = forms.CharField(
        label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def clean(self) -> dict:
        data = super().clean()
        if data.get("password") and data.get("password") != data.get("password_confirm"):
            self.add_error("password_confirm", "Passwords don't match.")
        return data


class ProductForm(forms.Form):
    name = forms.CharField(max_length=200)
    category = forms.TypedChoiceField(coerce=int, required=False, empty_value=None)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=False)
    price = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"))
    stock = forms.IntegerField(min_value=0)
    image_url = forms.URLField(required=False, label="Image URL")
    is_active = forms.BooleanField(required=False, initial=True, label="Visible to customers")

    def __init__(self, *args, categories: list[dict], **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = [("", "— No category —")] + [
            (category["id"], category["name"]) for category in categories
        ]

    def to_payload(self) -> dict:
        data = self.cleaned_data
        return {
            "name": data["name"],
            "category": data["category"],
            "description": data["description"],
            "price": str(data["price"]),
            "stock": data["stock"],
            "image_url": data["image_url"],
            "is_active": data["is_active"],
        }


PHONE_VALIDATOR = RegexValidator(
    r"^\+?[0-9][0-9 ()\-]{5,19}$", message="Enter a valid phone number, for example +63 912 345 6789."
)


class AddressForm(forms.Form):
    label = forms.ChoiceField(
        choices=[("home", "Home"), ("office", "Office"), ("other", "Other")],
        widget=forms.RadioSelect,
        initial="home",
    )
    custom_label = forms.CharField(
        max_length=50,
        required=False,
        label="Name for this address",
        error_messages={"max_length": "Keep the name to 50 characters or fewer."},
        widget=forms.TextInput(attrs={"autocomplete": "off", "aria-describedby": "custom-label-hint"}),
    )
    recipient_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    phone = forms.CharField(
        max_length=20,
        validators=[PHONE_VALIDATOR],
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "inputmode": "tel"}),
    )
    line1 = forms.CharField(
        max_length=200, label="Address", widget=forms.TextInput(attrs={"autocomplete": "address-line1"})
    )
    line2 = forms.CharField(
        max_length=200,
        required=False,
        label="Address line 2 (optional)",
        widget=forms.TextInput(attrs={"autocomplete": "address-line2"}),
    )
    city = forms.CharField(max_length=100, widget=forms.TextInput(attrs={"autocomplete": "address-level2"}))
    region = forms.CharField(
        max_length=100,
        required=False,
        label="Region (optional)",
        widget=forms.TextInput(attrs={"autocomplete": "address-level1"}),
    )
    postcode = forms.CharField(
        max_length=20,
        required=False,
        label="Postcode (optional)",
        widget=forms.TextInput(attrs={"autocomplete": "postal-code"}),
    )
    country = forms.ChoiceField(
        error_messages={"required": "Choose a country.", "invalid_choice": "Choose a country from the list."},
        widget=forms.Select(attrs={"autocomplete": "country"}),
    )
    is_default = forms.BooleanField(required=False, label="Use as my default address")

    def __init__(self, *args, countries: list[tuple[str, str]], **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["country"].choices = [("", "Choose a country")] + countries

    def clean(self) -> dict:
        data = super().clean()
        if data.get("label") != "other" and "custom_label" in data:
            data["custom_label"] = ""
        return data

    def to_payload(self) -> dict:
        data = self.cleaned_data
        return {
            "label": data["label"],
            "custom_label": data["custom_label"],
            "is_default": data["is_default"],
            "recipient_name": data["recipient_name"],
            "phone": data["phone"],
            "line1": data["line1"],
            "line2": data["line2"],
            "city": data["city"],
            "region": data["region"],
            "postcode": data["postcode"],
            "country": data["country"],
        }


def address_initial(address: dict) -> dict:
    """Form values for editing a saved address."""
    return {name: address[name] for name in AddressForm.base_fields}


def new_address_initial(addresses: list[dict], full_name: str) -> dict:
    """Form values for a new address, given the user's saved ones in the API's order.

    The API lists the default first and the rest newest-updated first, so the first
    address is the default when there is one and the newest otherwise.
    """
    reference = next((address for address in addresses if address["is_default"]), None)
    if reference is None and addresses:
        reference = addresses[0]
    return {
        "recipient_name": reference["recipient_name"] if reference else full_name,
        "country": reference["country"] if reference else "",
        "is_default": not addresses,
    }


class AddToCartForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=99, initial=1)
