from django.contrib import admin

from .models import Category, Order, OrderItem, Product


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
    list_display = ["id", "user", "status", "created_at"]
    list_filter = ["status"]
    list_editable = ["status"]
    inlines = [OrderItemInline]
