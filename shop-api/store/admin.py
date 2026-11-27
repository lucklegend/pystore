from django.contrib import admin
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .models import Category, DeliveryAddress, Order, OrderItem, Product

SHIPPING_FIELDS = [
    "shipping_label",
    "shipping_custom_label",
    "shipping_recipient_name",
    "shipping_phone",
    "shipping_line1",
    "shipping_line2",
    "shipping_city",
    "shipping_region",
    "shipping_postcode",
    "shipping_country",
    "shipping_country_name",
]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "price", "stock", "is_active", "updated_at"]
    list_filter = ["is_active", "category"]
    list_editable = ["price", "stock", "is_active"]
    search_fields = ["name", "description"]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "quantity", "unit_price"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "ordered_items", "order_total", "status", "created_at"]
    list_filter = ["status"]
    list_editable = ["status"]
    inlines = [OrderItemInline]
    fieldsets = [
        (None, {"fields": ["user", "status"]}),
        (_("Shipping address"), {"fields": SHIPPING_FIELDS}),
    ]
    # The address is a copy taken at checkout, and stays as it was.
    readonly_fields = SHIPPING_FIELDS

    def get_queryset(self, request):
        # One query for every listed order's items, rather than one per row.
        return super().get_queryset(request).select_related("user").prefetch_related("items__product")

    @admin.display(description=_("Items"))
    def ordered_items(self, order: Order):
        return format_html_join(
            mark_safe("<br>"), "{} × {}", ((item.quantity, item.product.name) for item in order.items.all())
        )

    @admin.display(description=_("Total"))
    def order_total(self, order: Order):
        return order.total


@admin.register(DeliveryAddress)
class DeliveryAddressAdmin(admin.ModelAdmin):
    list_display = ["user", "address_label", "is_default", "recipient_name", "city", "country"]
    list_select_related = ["user"]
    search_fields = ["recipient_name", "user__username", "city"]
    # Changing the default here would skip store.addresses, which clears the user's old one.
    readonly_fields = ["is_default"]

    @admin.display(description=_("Label"))
    def address_label(self, address: DeliveryAddress):
        return address.label_display
