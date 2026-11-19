"""Credentials used by the test suite, so no password is written into the tests.

Each value is read from the environment first, then from a `.env.test` file in
the project root (see `.env.test.example`). Anything still unset is generated
fresh for the run, so the suite works with no setup at all.
"""
import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

ENV_FILE = Path(__file__).resolve().parent.parent / ".env.test"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, skipping blanks and # comments."""
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def resolve_secret(name: str, file_values: dict[str, str]) -> str:
    return os.environ.get(name) or file_values.get(name) or secrets.token_urlsafe(18)


_file_values = read_env_file(ENV_FILE)

# Must pass Django's password validators: 8+ characters, not common, not all digits.
USER_PASSWORD = resolve_secret("TEST_USER_PASSWORD", _file_values)
WRONG_PASSWORD = resolve_secret("TEST_WRONG_PASSWORD", _file_values)

if USER_PASSWORD == WRONG_PASSWORD:
    raise ImproperlyConfigured("TEST_USER_PASSWORD and TEST_WRONG_PASSWORD must differ.")
