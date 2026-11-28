# shop-api

Django + Django REST Framework backend for the shop, and the home of the Wagtail CMS. It owns customers, login tokens, categories, products, orders, CMS pages, images and documents. The storefront ([shop-web](../shop-web)) reads and writes everything through this API and has no database of its own.

## Run it

Requires Python 3.10+ (developed on 3.12). `py -3.12` picks the version even if an older Python is installed. Skip the `venv` line if `.venv` already exists.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_store         # demo categories and products
.\.venv\Scripts\python manage.py bootstrap_site     # creates the Home and About pages (new installs only)
.\.venv\Scripts\python manage.py createsuperuser    # full admin and CMS access
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8001
```

- Browsable API: http://127.0.0.1:8001/api/ (token only: the `/admin/` login cookie is not accepted, so it shows what an anonymous visitor sees)
- Django admin: http://127.0.0.1:8001/admin/ (you can also change order status here, and create staff)
- Wagtail CMS: http://127.0.0.1:8001/cms/

Upgrading an install that has CMS content in shop-web? Skip `bootstrap_site` and follow the migration runbook below.

## Endpoints

Authenticate with the header `Authorization: Token <key>`. The API takes no cookie sessions.

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/api/auth/register/` | anyone | `{username, email, password}` → `{token, user}` |
| POST | `/api/auth/login/` | anyone | `{username, password}` → `{token, user}` |
| POST | `/api/auth/logout/` | logged in | signs the user out everywhere: deletes the token and ends the user's CMS and `/admin/` sessions |
| GET | `/api/auth/me/` | logged in | current user |
| POST | `/api/auth/handoff/` | logged in (token) | `{state}` → `201 {code, expires_in}`. Mints a one-time code for the CMS. 403 unless the user is CMS-eligible |
| POST | `/api/auth/handoff/redeem/` | the storefront | `{code, state}` plus header `X-SSO-Client-Secret` → login shape. Throttled. One generic 400 for every bad code |
| GET | `/api/cms/pages/resolve/` | anyone | a page or redirect payload for the storefront to render |
| GET | `/api/cms/navigation/` | anyone | menu items in tree order |
| GET | `/api/categories/` | anyone | not paginated |
| POST/PUT/PATCH/DELETE | `/api/categories/…` | staff | |
| GET | `/api/products/` | anyone | `?search=`, `?category=<id>`, `?ids=1,2`, `?ordering=price`, `?page=`, `?page_size=` |
| POST/PUT/PATCH/DELETE | `/api/products/…` | staff | delete returns 409 if the product is in an order |
| GET | `/api/countries/` | anyone | `[{code, name}]`, ISO 3166-1 alpha-2, sorted by name, not paginated |
| GET/POST | `/api/addresses/` | logged in | your own delivery addresses, default first, not paginated. 400 `{detail}` past 20 addresses |
| GET/PUT/PATCH/DELETE | `/api/addresses/<id>/` | owner only, staff included | someone else's address is a 404 |
| GET | `/api/orders/` | logged in | your own orders; staff see all. Each carries `shipping_address`, or `null` on orders from before addresses |
| POST | `/api/orders/` | logged in | `{items: [{product, quantity}], delivery_address: <id>}`; checks and reserves stock. A missing address or one that isn't yours is 400 `{delivery_address: ["Choose one of your delivery addresses."]}` |
| POST | `/api/orders/<id>/cancel/` | owner or staff | pending orders only; stock is returned |

Customers only see active products. Staff see inactive ones too.

**Delivery addresses.** Writable fields: `label` (`home`, `office` or `other`), `custom_label` (up to 50 characters, kept only with `other`), `is_default`, `recipient_name`, `phone`, `line1`, `line2`, `city`, `region`, `postcode`, `country` (alpha-2 code). Responses add `id`, `label_display`, `country_display`, `created_at` and `updated_at`.
- A user has at most one default. Your first address becomes the default whatever you send. Setting `is_default: true` on another moves the default there. Setting it false, or deleting the default, leaves you with none: nothing is promoted.
- Writes are throttled to 30 a minute per user.
- An order copies the address at checkout, so editing or deleting it later doesn't change past orders.

## The CMS

Wagtail's admin is mounted once, at `/cms/`. Pages are rendered by the storefront, not here: any other slash-terminated path (for example `/about/`) redirects to the storefront.

| Route | What |
|---|---|
| `/cms/` | Wagtail admin |
| `/cms/login/`, `/cms/logout/` | Wagtail's views wrapped with single sign-on (logout is POST only) |
| `/cms/sso/authorize/`, `/cms/sso/callback/` | the shop-api half of the SSO handshake |
| `/documents/…` | Wagtail document downloads |
| `/media/…` | uploaded images and documents, served by Django only while `DJANGO_DEBUG=1` |

**Who can use it.** A user needs to be active and either a superuser or staff. A staff user who is not a superuser is put in Wagtail's **Moderators** group automatically: they can add, edit and publish pages, and do not see Users or Settings. A superuser has the full admin. Customers are rejected. Create CMS staff in `/admin/` or with `createsuperuser`; users created in Wagtail's own user admin are not staff and cannot sign in. Removing someone's staff rights locks them out of the CMS at once, but the storefront keeps showing "CMS" and "Manage" until they log in again.

**Single sign-on across the two hosts.** One shop-api account covers the storefront (`:8080`) and the CMS (`:8001`).
- Opening `/cms/` while logged in as staff on the storefront signs you in silently, with no password. If that can't work (not logged in there, a customer, storefront unreachable, expired link), you get the normal Wagtail form, with one message where there is something to say. Only one silent attempt is made per session.
- Signing in with a password on the CMS form signs you in on the storefront too.
- Logging out on either side clears both. Wagtail's "Log out" signs the user out everywhere, bounces through the storefront and returns to the CMS login. A per-user sign-out counter ends every other CMS and `/admin/` session on its next request, even one whose session key has changed since login. The API takes tokens only, so deleting the token ends API access.
- A staff API token can be exchanged for a CMS session, by design. Treat staff tokens as CMS credentials.
- Sessions created by SSO last two weeks, whatever "Remember me" says.
- Run both servers. If the storefront is down, signing in to or out of the CMS ends on a browser error. Open `http://127.0.0.1:8001/cms/` again and you are in.

**Published changes appear on the storefront within a minute.** Wagtail redirects now apply only to slash-terminated paths such as `/old/`, not to every 404 as before. Page preview is turned off.

**Documents and images are public.** `WAGTAILDOCS_SERVE_METHOD` is `"direct"`, so anyone with the URL can fetch a file. Wagtail's private collections do **not** protect documents in this mode, and editors must not upload private files. Never add `html`, `htm`, `svg` or `xml` to `WAGTAILDOCS_EXTENSIONS` or to the image extensions: media shares an origin with the admin, so such an upload would be stored XSS against superusers.

## Migrating the CMS from shop-web

For an install whose pages live in `shop-web/db.sqlite3`. `import_legacy_cms` copies pages, revisions, images, documents, redirects, tags and the Site into shop-api and verifies them. Do it once.

1. Before the switch, save the HTML of `/` and `/about/` from the old shop-web.
2. Copy `shop-web/db.sqlite3` to `shop-api/legacy_cms.sqlite3` (or point `LEGACY_CMS_DATABASE` at it). It is only read.
3. `manage.py migrate`. **Never run `migrate --database legacy_cms`**: Wagtail's migrations cannot build a second database.
4. `manage.py import_legacy_cms --dry-run`. It runs every step and check, rolls back, and removes any files it copied.
5. `manage.py import_legacy_cms`.
6. Deploy the new shop-web and shop-api, then compare the main content of `/` and `/about/` with the saved HTML.
7. Once it is verified, delete `shop-web/db.sqlite3` and `shop-api/legacy_cms.sqlite3`.
8. Create CMS staff in `/admin/` or with `createsuperuser`.

Notes:
- The command fails and writes nothing on any mismatch. If shop-api already has CMS pages it exits 1; rerun with `--replace` to replace the pages `bootstrap_site` made. `--replace` still refuses while shop-api has images, documents, collections or tags, because deleting them would delete files the import is about to copy.
- Options: `--media-source` (shop-web's media folder, default `../shop-web/media`), `--site-url` (default `STOREFRONT_URL`) and `--database` (default `legacy_cms`).
- Users are matched by **username**: a source `admin` maps to whichever shop-api user is named `admin`. Unknown usernames are cleared and reported.
- Everyone is logged out once at the switch, because the storefront moves to signed-cookie sessions with new cookie names. Existing CMS sessions are also signed out once, because this deploy adds the sign-out counter (`migrate` creates it); silent SSO usually signs staff straight back in.

## Configuration

| Variable | Default |
|---|---|
| `DJANGO_SECRET_KEY` | dev-only key. **Required** (non-default) when `DJANGO_DEBUG=0` |
| `DJANGO_DEBUG` | `1` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `DJANGO_SECURE_COOKIES` | `0`. Set `1` over HTTPS: cookies get the `__Host-` prefix and `Secure`. Pair it with HSTS in the web server |
| `DJANGO_NUM_PROXIES` | `0`. Reverse proxies in front of shop-api, used for the throttle's client address. A wrong value lets clients dodge the throttle with a forged `X-Forwarded-For` |
| `STOREFRONT_URL` | `http://127.0.0.1:8080` |
| `SHOP_API_PUBLIC_URL` | `http://127.0.0.1:8001` (also the base of `MEDIA_URL`) |
| `SSO_CLIENT_SECRET` | dev-only value. Must equal shop-web's. **Required** (non-default) when `DJANGO_DEBUG=0`; use `secrets.token_urlsafe(32)` or stronger |
| `SSO_CODE_TTL_SECONDS` | `60` |
| `LEGACY_CMS_DATABASE` | `legacy_cms.sqlite3` next to `manage.py` (import input only) |

`requirements.txt` pins `djangorestframework>=3.18.2,<3.19`.

## Deploying

- **Secrets.** With `DJANGO_DEBUG=0` the server refuses to start without non-default `DJANGO_SECRET_KEY` and `SSO_CLIENT_SECRET`.
- **HTTPS.** Set `DJANGO_SECURE_COOKIES=1`. Behind a TLS-terminating proxy, the proxy must pass the original scheme and `SECURE_PROXY_SSL_HEADER` must be set to match. The settings do not set it, and without it an `http://` `next` to an allowed host passes the redirect check. The shop-web to shop-api link (`SHOP_API_URL`) carries the client secret and tokens, so it must be HTTPS or a private network.
- **Media.** Django serves `/media/` only with `DJANGO_DEBUG=1`. In production the web server must serve `MEDIA_ROOT` at `/media/`, with `X-Content-Type-Options: nosniff`.
- **Throttle.** The redeem throttle uses a per-process cache, so with several workers the limit applies per worker.
- **Sessions.** Schedule `manage.py clearsessions` (daily is fine). Anonymous visits to `/cms/login/` create session rows that nothing else removes.
- **Login attempts.** There is no rate limit on password attempts at `/cms/login/`. Add one in the web server.
