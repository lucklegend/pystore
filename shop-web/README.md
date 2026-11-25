# shop-web

The storefront. Customers browse products, keep a cart, log in and place orders. It has **no database**: shop data and CMS pages (home page text, About and so on) both come from [shop-api](../shop-api) over REST. Sessions live in signed cookies. Editors work in the Wagtail CMS, which now runs in shop-api at `http://127.0.0.1:8001/cms/`.

## Run it

Requires Python 3.10+ (developed on 3.12). `py -3.12` picks the version even if an older Python is installed. Skip the `venv` line if `.venv` already exists.

Start shop-api first (port 8001). Then:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8080
```

There is no `migrate` step. Run both servers: if the storefront is down, signing in to or out of the CMS ends on a browser error. Open `http://127.0.0.1:8001/cms/` again and you are in.

- Storefront: http://127.0.0.1:8080/
- CMS: http://127.0.0.1:8001/cms/ (the "CMS" link in the storefront nav, shown to staff)
- `http://127.0.0.1:8080/cms/` on this host is a 404.

## One account

Accounts live in shop-api only. A login is stored in the session as the API token. Staff see "Manage" and "CMS" links in the nav. Signing in or out on either host is picked up by the other. See [the root README](../README.md#one-account) for the full behaviour.

The routes under `/account/sso/` (`begin`, `authorize`, `callback`, `logout`) are the storefront half of that. Codes are redeemed server to server with `SSO_CLIENT_SECRET`, so `SHOP_API_URL` must be HTTPS or a private network in production.

Published CMS changes appear on the storefront within a minute (`CMS_CACHE_SECONDS`). If shop-api is down, `/` and `/about/` show the "Shop temporarily unavailable" page, like every `/shop/` page.

## Layout

- `home/`: renders CMS pages. `cms.py` fetches and caches a page payload from shop-api, `views.py` picks a template per page type (`HomePage` shows the newest products, `StandardPage` is plain content) and applies CMS redirects. `config/urls.py` ends with a catch-all that sends slash-terminated paths here.
- `storefront/api.py`: `ShopApi`, the only code that talks to shop-api.
- `storefront/sso.py` and `storefront/views/sso.py`: the SSO handshake.
- `storefront/middleware.py`: attaches `request.shop_api` and `request.shop_user`, and turns unhandled API errors into a login redirect (401), a 404, or an error page.
- `storefront/cart.py`: the session cart (product id → quantity). Prices are always re-read from the API.
- `storefront/views/`: `auth.py`, `shop.py` (catalogue, cart, checkout, orders), `manage.py` (staff product CRUD), `sso.py`.

## Configuration

| Variable | Default |
|---|---|
| `SHOP_API_URL` | `http://127.0.0.1:8001/api` |
| `SHOP_API_PUBLIC_URL` | `http://127.0.0.1:8001` (where the browser reaches shop-api and the CMS) |
| `SHOP_API_TIMEOUT` | `5` (seconds) |
| `SSO_CLIENT_SECRET` | dev-only value. Must equal shop-api's. **Required** when `DJANGO_DEBUG=0` |
| `CMS_CACHE_SECONDS` | `60` |
| `SESSION_COOKIE_AGE` | `604800` (7 days) |
| `DJANGO_SECRET_KEY` | dev-only key. **Required** (non-default) when `DJANGO_DEBUG=0` |
| `DJANGO_DEBUG` | `1` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `DJANGO_SECURE_COOKIES` | `0`. Set `1` over HTTPS: cookies get the `__Host-` prefix and `Secure` |

With `DJANGO_DEBUG=0` the server refuses to start unless `DJANGO_SECRET_KEY` and `SSO_CLIENT_SECRET` are set to non-default values. Generate `SSO_CLIENT_SECRET` with `python -c "import secrets; print(secrets.token_urlsafe(32))"` or stronger.
