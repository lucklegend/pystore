import re
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from home.views import storefront_redirect


def media_patterns(debug, media_url, media_root):
    """Serve uploads in development only; in production the web server serves MEDIA_ROOT.

    django.conf.urls.static.static() is not used because it returns nothing for an absolute MEDIA_URL,
    and ours is one (it carries SHOP_API_PUBLIC_URL), so the prefix is taken from the URL's path.
    """
    prefix = urlsplit(media_url).path.strip("/")
    if not debug or not prefix:
        return []
    return [re_path(rf"^{re.escape(prefix)}/(?P<path>.*)$", serve, {"document_root": media_root})]


# Wagtail's admin is mounted once, at settings.CMS_URL_PREFIX, which is where CmsStaffOnlyMiddleware
# gates. accounts.cms_urls comes first so its login and logout shadow Wagtail's. wagtail.urls is
# not included: shop-api serves no pages.
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/cms/", include("home.urls")),
    path("api/", include("store.urls")),
    path("cms/", include("accounts.cms_urls")),
    path("cms/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    *media_patterns(settings.DEBUG, settings.MEDIA_URL, settings.MEDIA_ROOT),
    # Last, so it only catches what nothing else routes. Wagtail reverses this name to build every page
    # URL; the pattern is Wagtail's own and must not widen, or the redirect becomes an open one.
    re_path(r"^((?:[\w\-]+/)*)$", storefront_redirect, name="wagtail_serve"),
]
