from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django_countries.fields import CountryField


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    stock = models.PositiveIntegerField(default=0)
    image_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True, help_text="Inactive products are hidden from customers.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class DeliveryAddress(models.Model):
    class Label(models.TextChoices):
        HOME = "home", "Home"
        OFFICE = "office", "Office"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="delivery_addresses"
    )
    label = models.CharField(max_length=10, choices=Label.choices, default=Label.HOME)
    custom_label = models.CharField(max_length=50, blank=True, help_text="Only used when the label is Other.")
    # Set through store.addresses, which keeps each user to at most one default.
    is_default = models.BooleanField(default=False)
    recipient_name = models.CharField(max_length=100)
    phone = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                r"^\+?[0-9][0-9 ()\-]{5,19}$",
                message="Enter a valid phone number, for example +63 912 345 6789.",
            )
        ],
    )
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    region = models.CharField(max_length=100, blank=True)
    postcode = models.CharField(max_length=20, blank=True)
    country = CountryField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-updated_at"]
        verbose_name_plural = "delivery addresses"
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=Q(is_default=True), name="store_one_default_address_per_user"
            ),
            models.CheckConstraint(
                condition=Q(label="other") | Q(custom_label=""),
                name="store_address_custom_label_only_for_other",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label_display}: {self.recipient_name}, {self.city}"

    @property
    def label_display(self) -> str:
        return resolve_label(self.label, self.custom_label)

    def snapshot_fields(self) -> dict[str, str]:
        """The Order.shipping_* values that freeze this address onto an order."""
        return {
            "shipping_label": self.label,
            "shipping_custom_label": self.custom_label,
            "shipping_recipient_name": self.recipient_name,
            "shipping_phone": self.phone,
            "shipping_line1": self.line1,
            "shipping_line2": self.line2,
            "shipping_city": self.city,
            "shipping_region": self.region,
            "shipping_postcode": self.postcode,
            "shipping_country": self.country.code,
            "shipping_country_name": self.country.name,
        }


def resolve_label(label: str, custom_label: str) -> str:
    """The name shown for an address: an Other's own name if it has one, else the choice's name."""
    if label == DeliveryAddress.Label.OTHER and custom_label:
        return custom_label
    return DeliveryAddress.Label(label).label


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    # The delivery address is copied at checkout, like OrderItem.unit_price, so editing or deleting
    # the saved address doesn't rewrite past orders. Blank on orders placed before addresses existed.
    shipping_label = models.CharField(max_length=10, blank=True, default="")
    shipping_custom_label = models.CharField(max_length=50, blank=True, default="")
    shipping_recipient_name = models.CharField(max_length=100, blank=True, default="")
    shipping_phone = models.CharField(max_length=20, blank=True, default="")
    shipping_line1 = models.CharField(max_length=200, blank=True, default="")
    shipping_line2 = models.CharField(max_length=200, blank=True, default="")
    shipping_city = models.CharField(max_length=100, blank=True, default="")
    shipping_region = models.CharField(max_length=100, blank=True, default="")
    shipping_postcode = models.CharField(max_length=20, blank=True, default="")
    shipping_country = models.CharField(max_length=2, blank=True, default="")
    # Frozen too, so a renamed country in a later django-countries release can't change a past order.
    shipping_country_name = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Order #{self.pk} ({self.get_status_display()})"

    @property
    def shipping_address(self) -> dict[str, str] | None:
        """The frozen address in a saved address's shape, or None for an order without one."""
        if self.shipping_line1 == "":
            return None
        return {
            "label": self.shipping_label,
            "custom_label": self.shipping_custom_label,
            "label_display": resolve_label(self.shipping_label, self.shipping_custom_label),
            "recipient_name": self.shipping_recipient_name,
            "phone": self.shipping_phone,
            "line1": self.shipping_line1,
            "line2": self.shipping_line2,
            "city": self.shipping_city,
            "region": self.shipping_region,
            "postcode": self.shipping_postcode,
            "country": self.shipping_country,
            "country_display": self.shipping_country_name,
        }

    @property
    def total(self) -> Decimal:
        return sum((item.subtotal for item in self.items.all()), Decimal("0.00"))


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Price is copied at checkout so later price edits don't rewrite past orders.
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self) -> str:
        return f"{self.quantity} × {self.product}"

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity
