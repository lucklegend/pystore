from django.db.models import ProtectedError, QuerySet
from django_countries import countries
from rest_framework import filters, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from .addresses import create_address, delete_address, update_address
from .models import Category, DeliveryAddress, Order, Product
from .permissions import IsStaffOrReadOnly
from .serializers import (
    CategorySerializer,
    DeliveryAddressSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    ProductSerializer,
)
from .services import cancel_order, place_order


def parse_id_list(raw: str) -> list[int]:
    return [int(part) for part in raw.split(",") if part.strip().isdigit()]


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsStaffOrReadOnly]
    pagination_class = None


class ProductViewSet(viewsets.ModelViewSet):
    """Products. Customers see active products only; staff see and manage everything.

    Query params: ?search=, ?category=<id>, ?ids=1,2,3, ?ordering=price|-price|name|-created_at
    """

    serializer_class = ProductSerializer
    permission_classes = [IsStaffOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["price", "name", "created_at"]

    def get_queryset(self) -> QuerySet[Product]:
        queryset = Product.objects.select_related("category")
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)

        category = self.request.query_params.get("category", "")
        if category.isdigit():
            queryset = queryset.filter(category_id=int(category))

        ids = self.request.query_params.get("ids")
        if ids is not None:
            queryset = queryset.filter(pk__in=parse_id_list(ids))
        return queryset

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "This product appears in orders and can't be deleted. Mark it inactive instead."},
                status=status.HTTP_409_CONFLICT,
            )


class CountryListView(APIView):
    """ISO 3166-1 countries for the address forms, sorted by name: [{code, name}, ...]."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request) -> Response:
        return Response([{"code": country.code, "name": country.name} for country in countries])


class DeliveryAddressViewSet(viewsets.ModelViewSet):
    """The caller's own delivery addresses, default first.

    Own-only for everyone, staff included, so another user's id is a 404 on every verb.
    """

    serializer_class = DeliveryAddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    # Per user, on writes only: shop-web lists the addresses on every cart view.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "addresses"

    def get_throttles(self) -> list[BaseThrottle]:
        if self.request.method in permissions.SAFE_METHODS:
            return []
        return super().get_throttles()

    def get_queryset(self) -> QuerySet[DeliveryAddress]:
        return DeliveryAddress.objects.filter(user=self.request.user)

    def perform_create(self, serializer: DeliveryAddressSerializer) -> None:
        serializer.instance = create_address(self.request.user, serializer.validated_data)

    def perform_update(self, serializer: DeliveryAddressSerializer) -> None:
        serializer.instance = update_address(serializer.instance, serializer.validated_data)

    def perform_destroy(self, instance: DeliveryAddress) -> None:
        delete_address(instance)


class OrderViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Orders. Customers see their own; staff see all."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> QuerySet[Order]:
        queryset = Order.objects.select_related("user").prefetch_related("items__product")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        return OrderCreateSerializer if self.action == "create" else OrderSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lines = [(line["product"], line["quantity"]) for line in serializer.validated_data["items"]]
        order = place_order(request.user, lines, serializer.validated_data.get("delivery_address"))
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        order = cancel_order(self.get_object())
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data)
