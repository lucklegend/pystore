"""HTTP client for shop-api. Every shop read and write in this project goes through here."""
from __future__ import annotations

from typing import Any, Mapping

import requests

NON_FIELD_KEYS = ("detail", "non_field_errors")


def flatten_errors(data: Any, prefix: str = "") -> list[str]:
    """Turn a DRF error payload (str, list or nested dict) into readable lines."""
    if data is None:
        return []
    if isinstance(data, str):
        return [f"{prefix}{data}"]
    if isinstance(data, list):
        return [line for item in data for line in flatten_errors(item, prefix)]
    if isinstance(data, dict):
        return [
            line
            for key, value in data.items()
            for line in flatten_errors(value, "" if key in NON_FIELD_KEYS else f"{prefix}{key}: ")
        ]
    return [f"{prefix}{data}"]


class ApiError(Exception):
    def __init__(self, status: int, data: Any):
        self.status = status
        self.data = data
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return " ".join(flatten_errors(self.data)) or f"Request failed ({self.status})."

    def field_errors(self) -> dict[str, list[str]]:
        if not isinstance(self.data, dict):
            return {}
        return {
            key: flatten_errors(value)
            for key, value in self.data.items()
            if key not in NON_FIELD_KEYS
        }

    def general_errors(self) -> list[str]:
        if not isinstance(self.data, dict):
            return flatten_errors(self.data)
        return [line for key in NON_FIELD_KEYS for line in flatten_errors(self.data.get(key))]


class ShopApi:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        http: requests.Session | None = None,
        timeout: float = 5.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.http = http or requests.Session()
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        try:
            response = self.http.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                params=params,
                json=json,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError(503, {"detail": "The shop service is unavailable. Please try again shortly."}) from exc

        data: Any = None
        if response.content:
            try:
                data = response.json()
            except ValueError:
                data = {"detail": response.text[:200]}
        if response.status_code >= 400:
            raise ApiError(response.status_code, data)
        return data

    # Auth
    def login(self, username: str, password: str) -> dict:
        return self._request("POST", "auth/login/", json={"username": username, "password": password})

    def register(self, username: str, email: str, password: str) -> dict:
        return self._request(
            "POST", "auth/register/", json={"username": username, "email": email, "password": password}
        )

    def logout(self) -> None:
        self._request("POST", "auth/logout/")

    # Catalogue
    def list_categories(self) -> list[dict]:
        return self._request("GET", "categories/")

    def list_products(self, params: Mapping[str, Any] | None = None) -> dict:
        return self._request("GET", "products/", params=params)

    def get_product(self, product_id: int) -> dict:
        return self._request("GET", f"products/{product_id}/")

    def create_product(self, payload: dict) -> dict:
        return self._request("POST", "products/", json=payload)

    def update_product(self, product_id: int, payload: dict) -> dict:
        return self._request("PUT", f"products/{product_id}/", json=payload)

    def delete_product(self, product_id: int) -> None:
        self._request("DELETE", f"products/{product_id}/")

    # Orders
    def list_orders(self, page: int = 1) -> dict:
        return self._request("GET", "orders/", params={"page": page})

    def get_order(self, order_id: int) -> dict:
        return self._request("GET", f"orders/{order_id}/")

    def create_order(self, lines: Mapping[int, int]) -> dict:
        items = [{"product": product_id, "quantity": quantity} for product_id, quantity in lines.items()]
        return self._request("POST", "orders/", json={"items": items})

    def cancel_order(self, order_id: int) -> dict:
        return self._request("POST", f"orders/{order_id}/cancel/")
