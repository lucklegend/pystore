# shop-api

Django + Django REST Framework backend for the shop. It owns customers, login tokens, categories, products and orders. The storefront ([shop-web](../shop-web)) reads and writes everything through this API.

## Run it

Requires Python 3.10+ (developed on 3.12).

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_store         # demo categories and products
.\.venv\Scripts\python manage.py createsuperuser    # a staff account can manage products
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8001
```

- Browsable API: http://127.0.0.1:8001/api/
- Django admin: http://127.0.0.1:8001/admin/ (you can also change order status here)

## Endpoints

Authenticate with the header `Authorization: Token <key>`.

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/api/auth/register/` | anyone | `{username, email, password}` → `{token, user}` |
| POST | `/api/auth/login/` | anyone | `{username, password}` → `{token, user}` |
| POST | `/api/auth/logout/` | logged in | deletes the token |
| GET | `/api/auth/me/` | logged in | current user |
| GET | `/api/categories/` | anyone | not paginated |
| POST/PUT/PATCH/DELETE | `/api/categories/…` | staff | |
| GET | `/api/products/` | anyone | `?search=`, `?category=<id>`, `?ids=1,2`, `?ordering=price`, `?page=`, `?page_size=` |
| POST/PUT/PATCH/DELETE | `/api/products/…` | staff | delete returns 409 if the product is in an order |
| GET | `/api/orders/` | logged in | your own orders; staff see all |
| POST | `/api/orders/` | logged in | `{items: [{product, quantity}]}`; checks and reserves stock |
| POST | `/api/orders/<id>/cancel/` | owner or staff | pending orders only; stock is returned |

Customers only see active products. Staff see inactive ones too.

## Configuration

| Variable | Default |
|---|---|
| `DJANGO_SECRET_KEY` | dev-only key — **set this in production** |
| `DJANGO_DEBUG` | `1` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` |
