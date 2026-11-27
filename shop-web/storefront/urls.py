from django.urls import path

from .views import addresses, auth, manage, shop, sso

app_name = "storefront"

urlpatterns = [
    path("account/login/", auth.login_view, name="login"),
    path("account/register/", auth.register_view, name="register"),
    path("account/logout/", auth.logout_view, name="logout"),
    path("account/sso/begin/", sso.sso_begin, name="sso_begin"),
    path("account/sso/authorize/", sso.sso_authorize, name="sso_authorize"),
    path("account/sso/callback/", sso.sso_callback, name="sso_callback"),
    path("account/sso/logout/", sso.sso_logout, name="sso_logout"),
    path("account/addresses/", addresses.address_list, name="address_list"),
    path("account/addresses/new/", addresses.address_create, name="address_create"),
    path("account/addresses/<int:address_id>/edit/", addresses.address_edit, name="address_edit"),
    path("account/addresses/<int:address_id>/default/", addresses.address_set_default, name="address_set_default"),
    path("account/addresses/<int:address_id>/delete/", addresses.address_delete, name="address_delete"),
    path("shop/", shop.product_list, name="product_list"),
    path("shop/products/<int:product_id>/", shop.product_detail, name="product_detail"),
    path("shop/cart/", shop.cart_detail, name="cart"),
    path("shop/cart/add/<int:product_id>/", shop.cart_add, name="cart_add"),
    path("shop/cart/update/<int:product_id>/", shop.cart_update, name="cart_update"),
    path("shop/cart/remove/<int:product_id>/", shop.cart_remove, name="cart_remove"),
    path("shop/cart/address/", shop.cart_address_add, name="cart_address_add"),
    path("shop/checkout/", shop.checkout, name="checkout"),
    path("shop/orders/", shop.order_list, name="order_list"),
    path("shop/orders/<int:order_id>/", shop.order_detail, name="order_detail"),
    path("shop/orders/<int:order_id>/cancel/", shop.order_cancel, name="order_cancel"),
    path("shop/manage/products/", manage.manage_products, name="manage_products"),
    path("shop/manage/products/new/", manage.product_create, name="product_create"),
    path("shop/manage/products/<int:product_id>/edit/", manage.product_edit, name="product_edit"),
    path("shop/manage/products/<int:product_id>/delete/", manage.product_delete, name="product_delete"),
]
