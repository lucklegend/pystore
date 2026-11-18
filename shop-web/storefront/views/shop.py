from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..api import ApiError
from ..cart import MAX_QUANTITY, Cart
from ..decorators import shop_login_required
from ..forms import AddToCartForm


def page_query(request: HttpRequest, page: int) -> str:
    query = request.GET.copy()
    query["page"] = str(page)
    return query.urlencode()


def product_list(request: HttpRequest) -> HttpResponse:
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    page_param = request.GET.get("page", "1")
    page = int(page_param) if page_param.isdigit() and int(page_param) > 0 else 1

    params = {"page": page}
    if search:
        params["search"] = search
    if category.isdigit():
        params["category"] = category

    data = request.shop_api.list_products(params)
    context = {
        "products": data["results"],
        "count": data["count"],
        "categories": request.shop_api.list_categories(),
        "search": search,
        "selected_category": category,
        "page": page,
        "prev_query": page_query(request, page - 1) if data["previous"] else None,
        "next_query": page_query(request, page + 1) if data["next"] else None,
    }
    return render(request, "storefront/product_list.html", context)


def product_detail(request: HttpRequest, product_id: int) -> HttpResponse:
    product = request.shop_api.get_product(product_id)
    return render(request, "storefront/product_detail.html", {"product": product, "form": AddToCartForm()})


@require_POST
def cart_add(request: HttpRequest, product_id: int) -> HttpResponse:
    form = AddToCartForm(request.POST)
    if form.is_valid():
        product = request.shop_api.get_product(product_id)
        Cart(request.session).add(product_id, form.cleaned_data["quantity"])
        messages.success(request, f"Added {product['name']} to your cart.")
    else:
        messages.error(request, "Choose a quantity between 1 and 99.")
    return redirect("storefront:cart")


def cart_detail(request: HttpRequest) -> HttpResponse:
    cart = Cart(request.session)
    lines = cart.lines
    items = []
    if lines:
        ids = ",".join(str(pk) for pk in lines)
        products = request.shop_api.list_products({"ids": ids, "page_size": 100})["results"]
        available = {product["id"]: product for product in products}
        if set(lines) - set(available):
            cart.keep_only(set(available))
            messages.warning(request, "Some items are no longer available and were removed from your cart.")
        for product_id, quantity in cart.lines.items():
            product = available[product_id]
            items.append({"product": product, "quantity": quantity, "subtotal": Decimal(product["price"]) * quantity})
    total = sum((item["subtotal"] for item in items), Decimal("0.00"))
    return render(
        request, "storefront/cart.html", {"items": items, "total": total, "max_quantity": MAX_QUANTITY}
    )


@require_POST
def cart_update(request: HttpRequest, product_id: int) -> HttpResponse:
    raw = request.POST.get("quantity", "")
    if raw.isdigit():
        Cart(request.session).set(product_id, int(raw))
    else:
        messages.error(request, "Quantity must be a whole number.")
    return redirect("storefront:cart")


@require_POST
def cart_remove(request: HttpRequest, product_id: int) -> HttpResponse:
    Cart(request.session).remove(product_id)
    return redirect("storefront:cart")


@require_POST
def checkout(request: HttpRequest) -> HttpResponse:
    if not request.shop_user:
        # Checkout is POST-only, so send them back to the cart after login, not here.
        messages.info(request, "Please log in to check out. Your cart is saved.")
        query = urlencode({"next": reverse("storefront:cart")})
        return redirect(f"{reverse('storefront:login')}?{query}")
    cart = Cart(request.session)
    if not cart.lines:
        messages.info(request, "Your cart is empty.")
        return redirect("storefront:cart")
    try:
        order = request.shop_api.create_order(cart.lines)
    except ApiError as error:
        if error.status != 400:
            raise
        messages.error(request, error.message)
        return redirect("storefront:cart")
    cart.clear()
    messages.success(request, f"Thanks! Order #{order['id']} has been placed.")
    return redirect("storefront:order_detail", order_id=order["id"])


@shop_login_required
def order_list(request: HttpRequest) -> HttpResponse:
    page_param = request.GET.get("page", "1")
    page = int(page_param) if page_param.isdigit() and int(page_param) > 0 else 1
    data = request.shop_api.list_orders(page)
    context = {
        "orders": data["results"],
        "prev_query": page_query(request, page - 1) if data["previous"] else None,
        "next_query": page_query(request, page + 1) if data["next"] else None,
    }
    return render(request, "storefront/order_list.html", context)


@shop_login_required
def order_detail(request: HttpRequest, order_id: int) -> HttpResponse:
    order = request.shop_api.get_order(order_id)
    return render(request, "storefront/order_detail.html", {"order": order})


@require_POST
@shop_login_required
def order_cancel(request: HttpRequest, order_id: int) -> HttpResponse:
    try:
        request.shop_api.cancel_order(order_id)
    except ApiError as error:
        if error.status != 400:
            raise
        messages.error(request, error.message)
    else:
        messages.success(request, f"Order #{order_id} was cancelled.")
    return redirect("storefront:order_detail", order_id=order_id)
