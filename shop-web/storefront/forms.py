from __future__ import annotations

from decimal import Decimal

from django import forms

from .api import ApiError


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


class AddToCartForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=99, initial=1)
