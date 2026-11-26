# 0001 — One database: move the CMS into shop-api, shop-web becomes a REST client

## Ask

The project should have one database. Today there are two:

- `shop-api/db.sqlite3` — shop users, auth tokens, categories, products, orders.
- `shop-web/db.sqlite3` — Wagtail CMS (pages incl. home page and its payment method section,
  images, documents, revisions), Django sessions, and an empty `auth_user` table that the CMS
  login (`/cms/login/`, `/django-admin/`) checks. shop-api accounts can't log into the CMS.

The user does not want two databases for one project, and wants every user credential to live
in shop-api only. Chosen direction (option B): move Wagtail and all of shop-web's data into
shop-api; shop-web keeps no database and reaches everything over REST.

## Requirements

1. **Wagtail lives in shop-api.** The CMS admin is served by shop-api and uses shop-api's own
   `auth_user` table directly — no shadow users, no syncing.
2. **Existing content survives.** Pages (home page, standard pages, payment method section),
   images, documents and their revisions currently in `shop-web/db.sqlite3` are carried over
   into shop-api's database, along with the media files they reference.
3. **shop-web has no database.** It renders CMS pages from shop-api over REST (e.g. Wagtail's
   API v2 or a purpose-built endpoint) alongside the shop data it already fetches. Sessions move
   off the database (e.g. signed cookies); assess what that exposes, since the session holds the
   API token.
4. **CMS access: staff and superusers only.** Normal (non-staff) users are rejected.
   - superuser → full Wagtail admin.
   - staff (not superuser) → CMS editor, not full admin.
   - Losing staff/superuser status in shop-api removes CMS access immediately, not at next login.
5. **One login covers both.** Logging in on the storefront also gets a staff/superuser into the
   CMS, and logging into the CMS also signs them into the storefront. Logging out from either
   clears both. The CMS and storefront now sit on different hosts (shop-api :8001, shop-web
   :8080) — the plan must solve this across hosts.
6. **Customers are unaffected.** Storefront login, registration, cart, checkout and orders behave
   as now.

## Pointers

- `shop-web/config/settings.py` — Wagtail apps, `DATABASES`, `SHOP_API_URL`.
- `shop-web/config/urls.py` — `/cms/`, `/django-admin/`, `/documents/`, Wagtail page routes.
- `shop-web/home/` — `HomePage`, `StandardPage` models and templates.
- `shop-web/storefront/` — API client (`api.py`), auth views, session helpers
  (`sign_in` / `current_user`), templates, tests.
- `shop-api/config/`, `shop-api/accounts/`, `shop-api/store/`.
- Follow the user's CLAUDE.md code rules.

## Decisions so far

- Option B chosen over keeping a read-only shadow user table in shop-web (option A): one source
  of truth, no syncing.
- Revocation is immediate.
