"""Saving and deleting delivery addresses, kept out of the views so the default and cap rules live in one place."""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from .models import DeliveryAddress

MAX_ADDRESSES_PER_USER = 20

# The only keys taken from `data`. Anything else (user, user_id, id, pk, timestamps) is dropped, so
# whatever a caller passes, it can't choose the owner or point the save at another row.
WRITABLE_FIELDS = (
    "label",
    "custom_label",
    "is_default",
    "recipient_name",
    "phone",
    "line1",
    "line2",
    "city",
    "region",
    "postcode",
    "country",
)


def writable(data: dict) -> dict:
    return {field: value for field, value in data.items() if field in WRITABLE_FIELDS}


def lock_addresses(user_id: int) -> list[int]:
    """Lock the user and their addresses for this transaction, and return the address ids.

    Locking the user row is what serialises two writes for the same user. Row locks on the
    addresses alone can't stop two concurrent creates from both counting 19, or both seeing none.
    """
    get_user_model().objects.select_for_update().only("pk").get(pk=user_id)
    addresses = DeliveryAddress.objects.select_for_update().filter(user_id=user_id)
    return list(addresses.values_list("pk", flat=True))


def create_address(user, data: dict) -> DeliveryAddress:
    """Save a new address for the user. Their first address is always the default."""
    with transaction.atomic():
        existing = lock_addresses(user.pk)
        if len(existing) >= MAX_ADDRESSES_PER_USER:
            raise ValidationError({"detail": f"You can save up to {MAX_ADDRESSES_PER_USER} addresses."})
        is_default = bool(data.get("is_default")) or not existing
        address = DeliveryAddress(**{**writable(data), "user": user, "is_default": is_default})
        if is_default:
            # Clear first, so the one-default-per-user index never sees two.
            DeliveryAddress.objects.filter(user=user, is_default=True).update(is_default=False)
        address.save()
    return address


def update_address(address: DeliveryAddress, data: dict) -> DeliveryAddress:
    """Apply the changes. Setting is_default moves the default here; clearing it leaves the user with none.

    Returns the saved row, a fresh copy: `address` itself is left as it was loaded.
    """
    with transaction.atomic():
        user_id = address.user_id
        lock_addresses(user_id)
        # Re-read under the lock, as cancel_order does, so the changes apply to the row as it is now
        # rather than to the copy loaded before the lock. Gone meanwhile is a 404: saving the old copy
        # would insert it again.
        current = DeliveryAddress.objects.filter(pk=address.pk, user_id=user_id).first()
        if current is None:
            raise NotFound()
        for field, value in writable(data).items():
            setattr(current, field, value)
        if current.is_default:
            DeliveryAddress.objects.filter(user_id=user_id, is_default=True).exclude(pk=current.pk).update(
                is_default=False
            )
        current.save()
    return current


def delete_address(address: DeliveryAddress) -> None:
    """Delete the address. Deleting the default promotes nothing, so the user is left without one."""
    address.delete()
