# shop-web

The Wagtail storefront. Editors manage content pages (home page text, About and so on) in the Wagtail CMS. Customers browse products, keep a cart, log in and place orders. All shop data comes from [shop-api](../shop-api) over REST; this project's own database holds only CMS pages and sessions.

## Run it

Start shop-api first (port 8001). Then:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py bootstrap_site     # creates the Home and About pages
.\.venv\Scripts\python manage.py createsuperuser    # a CMS editor account (separate from shop accounts)
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8080
```

- Storefront: http://127.0.0.1:8080/
- Wagtail CMS: http://127.0.0.1:8080/cms/

## Two kinds of login

| Account | Lives in | Used for |
|---|---|---|
| Shop customer / staff | shop-api | buying, viewing orders; staff also manage products at `/shop/manage/products/` |
| CMS editor | shop-web (Django auth) | editing pages at `/cms/` |

A shop login is stored in the session as the API token. Logging out of the shop doesn't log a CMS editor out.

## Layout

- `home/`: Wagtail page types. `HomePage` shows the newest products from the API. `StandardPage` is for plain content.
- `storefront/api.py`: `ShopApi`, the only code that talks to shop-api.
- `storefront/middleware.py`: attaches `request.shop_api` and `request.shop_user`, and turns unhandled API errors into a login redirect (401), a 404, or an error page.
- `storefront/cart.py`: the session cart (product id → quantity). Prices are always re-read from the API.
- `storefront/views/`: `auth.py`, `shop.py` (catalogue, cart, checkout, orders), `manage.py` (staff product CRUD).

## Configuration

| Variable | Default |
|---|---|
| `SHOP_API_URL` | `http://127.0.0.1:8001/api` |
| `SHOP_API_TIMEOUT` | `5` (seconds) |
| `DJANGO_SECRET_KEY` | dev-only key — **set this in production** |
| `DJANGO_DEBUG` | `1` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `WAGTAILADMIN_BASE_URL` | `http://127.0.0.1:8080` |
