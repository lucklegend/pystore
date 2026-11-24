"""Settings for the shop REST API.

Values that differ between environments come from environment variables;
the defaults are for local development only.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-api-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# The storefront (shop-web) and this project's own public address, for links and SSO redirects.
STOREFRONT_URL = os.environ.get("STOREFRONT_URL", "http://127.0.0.1:8080").rstrip("/")
SHOP_API_PUBLIC_URL = os.environ.get("SHOP_API_PUBLIC_URL", "http://127.0.0.1:8001").rstrip("/")
# Must equal shop-web's SSO_CLIENT_SECRET. The default is for development only.
SSO_CLIENT_SECRET = os.environ.get("SSO_CLIENT_SECRET", "dev-only-insecure-sso-secret-change-me")
SSO_CODE_TTL_SECONDS = int(os.environ.get("SSO_CODE_TTL_SECONDS", "60"))
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
    },
}

# Distinct from shop-web's names: browsers share cookies across ports on one host.
SESSION_COOKIE_NAME = "shopapi_sessionid"
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
CSRF_COOKIE_NAME = "shopapi_csrftoken"
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "0") == "1"

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
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        # Lets you use the browsable API after logging in at /admin/.
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_PAGINATION_CLASS": "store.pagination.StandardPagination",
    "PAGE_SIZE": 12,
    "DEFAULT_THROTTLE_RATES": {"sso": "30/min"},
}
