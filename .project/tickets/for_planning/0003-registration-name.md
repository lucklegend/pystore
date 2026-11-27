# 0003 — Ask for a name at registration

Filed 2026-11-28. Split out of ticket 0002 (delivery address book).

## What the user asked for

Registration asks the customer for their name, so it is stored on the account. Ticket 0002
pre-fills a new delivery address's recipient name from the account's `full_name`; today accounts
hold no name, so that pre-fill is usually empty.

## Where it touches

- shop-api `accounts/`: user model or profile, registration serializer, `/api/auth/me/` (0002 adds
  `full_name` to it).
- shop-web: registration form and template, account details page if one exists.

## Open questions for planning

- One full-name field, or first and last name?
- Required at registration, or optional with a prompt later?
- Can existing users add or edit their name from an account page?
