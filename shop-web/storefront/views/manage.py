"""Staff product CRUD. Writes go to shop-api, which rejects non-staff tokens."""
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from ..api import ApiError
from ..decorators import shop_staff_required
from ..forms import ProductForm, apply_api_errors
from .shop import page_query

PRODUCT_FIELDS = ("name", "category", "description", "price", "stock", "image_url", "is_active")


@shop_staff_required
def manage_products(request: HttpRequest) -> HttpResponse:
    page_param = request.GET.get("page", "1")
    page = int(page_param) if page_param.isdigit() and int(page_param) > 0 else 1
    search = request.GET.get("q", "").strip()
    params = {"page": page, "page_size": 20, "ordering": "name"}
    if search:
        params["search"] = search
    data = request.shop_api.list_products(params)
    context = {
        "products": data["results"],
        "search": search,
        "prev_query": page_query(request, page - 1) if data["previous"] else None,
        "next_query": page_query(request, page + 1) if data["next"] else None,
    }
    return render(request, "storefront/manage/product_list.html", context)


def save_product(request: HttpRequest, product: dict | None) -> HttpResponse:
    """Shared create/edit flow: product is None for create."""
    categories = request.shop_api.list_categories()
    initial = {field: product[field] for field in PRODUCT_FIELDS} if product else None
    form = ProductForm(request.POST or None, initial=initial, categories=categories)

    if request.method == "POST" and form.is_valid():
        try:
            if product:
                saved = request.shop_api.update_product(product["id"], form.to_payload())
            else:
                saved = request.shop_api.create_product(form.to_payload())
        except ApiError as error:
            if error.status != 400:
                raise
            apply_api_errors(form, error)
        else:
            messages.success(request, f"Saved {saved['name']}.")
            return redirect("storefront:manage_products")

    return render(request, "storefront/manage/product_form.html", {"form": form, "product": product})


@shop_staff_required
def product_create(request: HttpRequest) -> HttpResponse:
    return save_product(request, None)


@shop_staff_required
def product_edit(request: HttpRequest, product_id: int) -> HttpResponse:
    return save_product(request, request.shop_api.get_product(product_id))


@shop_staff_required
def product_delete(request: HttpRequest, product_id: int) -> HttpResponse:
    product = request.shop_api.get_product(product_id)
    if request.method == "POST":
        try:
            request.shop_api.delete_product(product_id)
        except ApiError as error:
            if error.status != 409:
                raise
            messages.error(request, error.message)
            return redirect("storefront:product_edit", product_id=product_id)
        messages.success(request, f"Deleted {product['name']}.")
        return redirect("storefront:manage_products")
    return render(request, "storefront/manage/product_confirm_delete.html", {"product": product})
