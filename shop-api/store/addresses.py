"""Saving and deleting delivery addresses, kept out of the views so the default and cap rules live in one place."""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from .models import DeliveryAddress

MAX_ADDRESSES_PER_USER = 20


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
        address = DeliveryAddress(**{**data, "user": user, "is_default": is_default})
        if is_default:
            # Clear first, so the one-default-per-user index never sees two.
            DeliveryAddress.objects.filter(user=user, is_default=True).update(is_default=False)
        address.save()
    return address


def update_address(address: DeliveryAddress, data: dict) -> DeliveryAddress:
    """Apply the changes. Setting is_default moves the default here; clearing it leaves the user with none."""
    with transaction.atomic():
        if address.pk not in lock_addresses(address.user_id):
            # Deleted while we waited for the lock. Saving now would insert it again.
            raise NotFound()
        for field, value in data.items():
            setattr(address, field, value)
        if address.is_default:
            DeliveryAddress.objects.filter(user_id=address.user_id, is_default=True).exclude(pk=address.pk).update(
                is_default=False
            )
        address.save()
    return address


def delete_address(address: DeliveryAddress) -> None:
    """Delete the address. Deleting the default promotes nothing, so the user is left without one."""
    address.delete()
