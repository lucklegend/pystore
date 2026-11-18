from django.db.models import ProtectedError, QuerySet
from rest_framework import filters, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from .models import Category, Order, Product
from .permissions import IsStaffOrReadOnly
from .serializers import (
    CategorySerializer,
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
        order = place_order(request.user, lines)
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        order = cancel_order(self.get_object())
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data)
