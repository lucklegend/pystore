from django_countries.serializer_fields import CountryField
from rest_framework import serializers

from .models import Category, DeliveryAddress, Order, OrderItem, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "stock",
            "image_url",
            "is_active",
            "category",
            "category_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_category_name(self, product: Product) -> str | None:
        return product.category.name if product.category else None


class DeliveryAddressSerializer(serializers.ModelSerializer):
    """A saved address. The owner and the default and cap rules are not here: see store.addresses.

    `user` stays out of `fields`, so it can't be written, and DRF builds no validator from the
    one-default-per-user constraint (which would block moving the default).
    """

    country = CountryField()
    label_display = serializers.CharField(read_only=True)
    country_display = serializers.CharField(source="country.name", read_only=True)

    class Meta:
        model = DeliveryAddress
        fields = [
            "id",
            "label",
            "custom_label",
            "label_display",
            "is_default",
            "recipient_name",
            "phone",
            "line1",
            "line2",
            "city",
            "region",
            "postcode",
            "country",
            "country_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs: dict) -> dict:
        # The label this save ends with: a PATCH that leaves it out keeps the saved one.
        if "label" in attrs:
            label = attrs["label"]
        elif self.instance is not None:
            label = self.instance.label
        else:
            label = DeliveryAddress.Label.HOME
        if label != DeliveryAddress.Label.OTHER:
            attrs["custom_label"] = ""
        return attrs


class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "quantity", "unit_price", "subtotal"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    # The frozen copy from checkout, or null on orders placed before addresses existed.
    shipping_address = serializers.DictField(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "username", "status", "created_at", "items", "total", "shipping_address"]


class OrderLineSerializer(serializers.Serializer):
    product = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class OrderCreateSerializer(serializers.Serializer):
    items = OrderLineSerializer(many=True, allow_empty=False)
    # A plain id, not a related field: place_order checks ownership and gives a missing id and
    # another user's id the same error, so the response can't tell which ids exist.
    delivery_address = serializers.IntegerField(min_value=1, required=False)
