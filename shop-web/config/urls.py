from django.conf import settings
from django.urls import include, path, re_path

from home.views import cms_page

urlpatterns = [
    path("", include("storefront.urls")),
]

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()

# CMS pages live in shop-api. Any slash-terminated path may be one, so this goes last.
urlpatterns += [re_path(r"^((?:[\w\-]+/)*)$", cms_page)]
