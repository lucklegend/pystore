# 0002 — Delivery address required to place an order

Filed 2026-11-26. Branch: `feature-checkout`.

## What the user asked for

On the cart page (http://127.0.0.1:8080/shop/cart/):

1. A delivery address setting, so a user can set up where their orders are shipped. Pre-fill it from
   the account details shop-api already holds (name, email) where they exist.
2. The Place Order button is disabled, or leads to adding an address, until the user has a delivery
   address. This is an online store, so every order needs somewhere to ship to.

Proposed by Claude when filing, to confirm at planning:

3. shop-api enforces it as well: placing an order without a delivery address is rejected, whatever
   client sends it.
4. Each order stores a copy of the address it ships to, so editing the saved address later doesn't
   change past orders. The order detail page shows it.

## Where it touches

- shop-api owns the data: `store/` (`Order`, `place_order` in `services.py`, `OrderCreateSerializer`,
  `OrderViewSet`), `accounts/` (user, `/api/auth/me/`).
- shop-web renders it over REST: `storefront/api.py` (`ShopApi`), `storefront/views/shop.py`
  (cart, checkout, order detail), cart and order templates, forms.

## Open questions for planning

- One saved address per user, or an address book to choose from at checkout?
- Which fields: recipient name, phone, street lines, city, region, postcode, country? Is phone
  required?
- Is the address its own settings page, entered inline on the cart page, or both?
- Guests: the cart works logged out. Should checkout ask them to log in first (as now), then for an
  address?

## Answers (user, 2026-11-28)

- **Address book.** A user can save many delivery addresses. Each one has a label/category such as
  Home, Office or Other. One must be picked before an order can be placed.
- **Fields.** Address and phone are required. Adjust the shop-api database (models + migrations) for
  it.
- **Where.** Both: a dedicated delivery-address settings page, and inline on the cart page so a user
  at the cart never has to leave it to add or pick one.
- **Guests.** Log in first (as now), then add or pick an address before placing the order.
- Proposed items 3 (shop-api rejects an order without a delivery address) and 4 (each order stores a
  copy of its address; order detail shows it) are accepted.
