from rest_framework import serializers

from .models import Category, Order, OrderItem, Product


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

    class Meta:
        model = Order
        fields = ["id", "username", "status", "created_at", "items", "total"]


class OrderLineSerializer(serializers.Serializer):
    product = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class OrderCreateSerializer(serializers.Serializer):
    items = OrderLineSerializer(many=True, allow_empty=False)
