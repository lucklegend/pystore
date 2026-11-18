from django.urls import path

from .views import auth, manage, shop

app_name = "storefront"

urlpatterns = [
    path("account/login/", auth.login_view, name="login"),
    path("account/register/", auth.register_view, name="register"),
    path("account/logout/", auth.logout_view, name="logout"),
    path("shop/", shop.product_list, name="product_list"),
    path("shop/products/<int:product_id>/", shop.product_detail, name="product_detail"),
    path("shop/cart/", shop.cart_detail, name="cart"),
    path("shop/cart/add/<int:product_id>/", shop.cart_add, name="cart_add"),
    path("shop/cart/update/<int:product_id>/", shop.cart_update, name="cart_update"),
    path("shop/cart/remove/<int:product_id>/", shop.cart_remove, name="cart_remove"),
    path("shop/checkout/", shop.checkout, name="checkout"),
    path("shop/orders/", shop.order_list, name="order_list"),
    path("shop/orders/<int:order_id>/", shop.order_detail, name="order_detail"),
    path("shop/orders/<int:order_id>/cancel/", shop.order_cancel, name="order_cancel"),
    path("shop/manage/products/", manage.manage_products, name="manage_products"),
    path("shop/manage/products/new/", manage.product_create, name="product_create"),
    path("shop/manage/products/<int:product_id>/edit/", manage.product_edit, name="product_edit"),
    path("shop/manage/products/<int:product_id>/delete/", manage.product_delete, name="product_delete"),
]
