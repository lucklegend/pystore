"""Settings for the storefront.

This project has no database. Products, customers, orders and CMS pages
live in shop-api and are reached over REST at SHOP_API_URL. Sessions are
signed cookies and cached CMS payloads live in process memory.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEV_SECRET_KEY = "dev-only-insecure-web-key-change-me"
DEV_SSO_CLIENT_SECRET = "dev-only-insecure-sso-secret-change-me"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

SHOP_API_URL = os.environ.get("SHOP_API_URL", "http://127.0.0.1:8001/api").rstrip("/")
SHOP_API_TIMEOUT = float(os.environ.get("SHOP_API_TIMEOUT", "5"))
SHOP_API_PUBLIC_URL = os.environ.get("SHOP_API_PUBLIC_URL", "http://127.0.0.1:8001").rstrip("/")
# Must equal shop-api's SSO_CLIENT_SECRET. The default is for development only.
SSO_CLIENT_SECRET = os.environ.get("SSO_CLIENT_SECRET", DEV_SSO_CLIENT_SECRET)
CMS_CACHE_SECONDS = int(os.environ.get("CMS_CACHE_SECONDS", "60"))

if not DEBUG:
    for _name, _value, _dev_default in (
        ("DJANGO_SECRET_KEY", SECRET_KEY, DEV_SECRET_KEY),
        ("SSO_CLIENT_SECRET", SSO_CLIENT_SECRET, DEV_SSO_CLIENT_SECRET),
    ):
        if not _value or _value == _dev_default:
            raise ImproperlyConfigured(f"{_name} must be set to a non-default value when DJANGO_DEBUG is off.")

# One switch for Secure and the __Host- prefix, so one can never be set without the other:
# a browser silently drops a __Host- cookie that is not Secure. __Host- also requires
# Path=/ and no Domain, which are the defaults and are left alone.
SECURE_COOKIES = os.environ.get("DJANGO_SECURE_COOKIES", "0") == "1"
COOKIE_PREFIX = "__Host-" if SECURE_COOKIES else ""

INSTALLED_APPS = [
    "home",
    "storefront",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "storefront.middleware.ShopApiMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "storefront.context_processors.shop",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {}

# The session lives in a signed cookie that holds the shop-api token. It is
# signed, not encrypted, and shop-api stays the place where a token is revoked.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_NAME = f"{COOKIE_PREFIX}shopweb_session"
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", str(7 * 24 * 60 * 60)))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_NAME = f"{COOKIE_PREFIX}shopweb_csrftoken"
CSRF_COOKIE_SECURE = SECURE_COOKIES

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
