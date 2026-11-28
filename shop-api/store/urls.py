from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, CountryListView, DeliveryAddressViewSet, OrderViewSet, ProductViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")
router.register("orders", OrderViewSet, basename="order")
router.register("addresses", DeliveryAddressViewSet, basename="address")

urlpatterns = [
    path("countries/", CountryListView.as_view(), name="country-list"),
    *router.urls,
]
