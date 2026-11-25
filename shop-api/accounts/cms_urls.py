"""CMS routes with single sign-on. Mounted at cms/ before Wagtail's admin URLs, so these login/ and logout/ win."""
from django.urls import path

from .cms_views import cms_login, cms_logout, sso_authorize, sso_callback

urlpatterns = [
    path("login/", cms_login, name="cms_login"),
    path("logout/", cms_logout, name="cms_logout"),
    path("sso/authorize/", sso_authorize, name="cms_sso_authorize"),
    path("sso/callback/", sso_callback, name="cms_sso_callback"),
]
