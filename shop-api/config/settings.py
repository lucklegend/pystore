"""Settings for the shop REST API.

Values that differ between environments come from environment variables;
the defaults are for local development only.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEV_SECRET_KEY = "dev-only-insecure-api-key-change-me"
DEV_SSO_CLIENT_SECRET = "dev-only-insecure-sso-secret-change-me"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# The storefront (shop-web) and this project's own public address, for links and SSO redirects.
STOREFRONT_URL = os.environ.get("STOREFRONT_URL", "http://127.0.0.1:8080").rstrip("/")
SHOP_API_PUBLIC_URL = os.environ.get("SHOP_API_PUBLIC_URL", "http://127.0.0.1:8001").rstrip("/")
# Must equal shop-web's SSO_CLIENT_SECRET. The default is for development only.
SSO_CLIENT_SECRET = os.environ.get("SSO_CLIENT_SECRET", DEV_SSO_CLIENT_SECRET)
SSO_CODE_TTL_SECONDS = int(os.environ.get("SSO_CODE_TTL_SECONDS", "60"))

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
# Earlier releases read these two instead. Ignoring them would quietly drop Secure on upgrade.
for _name in ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
    if _name in os.environ and "DJANGO_SECURE_COOKIES" not in os.environ:
        raise ImproperlyConfigured(f"{_name} is no longer read. Set DJANGO_SECURE_COOKIES instead, and unset {_name}.")
CMS_URL_PREFIX = "/cms/"
LEGACY_CMS_DATABASE = os.environ.get("LEGACY_CMS_DATABASE", str(BASE_DIR / "legacy_cms.sqlite3"))

INSTALLED_APPS = [
    "config.admin_site.ShopAdminConfig",  # django.contrib.admin, with Store listed first
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "accounts",
    "store",
    "home",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Needs request.user, and request._messages for the message it leaves on rejection.
    "django.contrib.messages.middleware.MessageMiddleware",
    "accounts.middleware.CmsStaffOnlyMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # project-wide overrides, e.g. admin/pagination.html
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
    # Read-only input for `import_legacy_cms`: a copy of shop-web's old CMS database.
    "legacy_cms": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": LEGACY_CMS_DATABASE,
        # Build the test copy from the models: migrating it runs Wagtail's data migrations,
        # which reach the default database and fail on its half-built content types.
        "TEST": {"MIGRATE": False},
    },
}

# Distinct from shop-web's names: browsers share cookies across ports on one host.
SESSION_COOKIE_NAME = f"{COOKIE_PREFIX}shopapi_sessionid"
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_NAME = f"{COOKIE_PREFIX}shopapi_csrftoken"
CSRF_COOKIE_SECURE = SECURE_COOKIES

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Absolute, so image and document URLs in CMS rich text work on the storefront host too.
MEDIA_URL = f"{SHOP_API_PUBLIC_URL}/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10_000

WAGTAIL_SITE_NAME = "Offsure Shop"
WAGTAILADMIN_BASE_URL = SHOP_API_PUBLIC_URL
WAGTAILDOCS_SERVE_METHOD = "direct"
WAGTAILDOCS_EXTENSIONS = ["csv", "docx", "key", "odt", "pdf", "pptx", "rtf", "txt", "xlsx", "zip"]

REST_FRAMEWORK = {
    # Token only, so logging out (which deletes the token) ends API access at once. A cookie session
    # signed in at /admin/ or /cms/ is not accepted here, which also keeps CSRF off the API.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_PAGINATION_CLASS": "store.pagination.StandardPagination",
    "PAGE_SIZE": 12,
    "DEFAULT_THROTTLE_RATES": {"sso": "30/min"},
    # Trusted proxies in front of shop-api. With 0, throttles key on REMOTE_ADDR and ignore
    # X-Forwarded-For, which any client can set. Behind N proxies that append to it, set N.
    "NUM_PROXIES": int(os.environ.get("DJANGO_NUM_PROXIES", "0")),
}
