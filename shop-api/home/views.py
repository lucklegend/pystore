"""Read-only CMS content for the storefront. shop-api serves no pages itself; shop-web renders these."""
from django.db.models import F
from django.http import Http404
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.contrib.redirects.models import Redirect
from wagtail.models import Site

from .serializers import PAGE_FIELDS, navigation_payload, page_payload


def default_site() -> Site:
    site = Site.objects.select_related("root_page").filter(is_default_site=True).first()
    if site is None:
        raise NotFound()
    return site


def redirect_response(site: Site, path: str) -> Response:
    # A redirect for this site wins over one for all sites, as in Wagtail's RedirectMiddleware.
    redirect = (
        Redirect.get_for_site(site)
        .filter(old_path=Redirect.normalise_path(path))
        .order_by(F("site").asc(nulls_last=True))
        .first()
    )
    if redirect is None or redirect.link is None:
        raise NotFound()
    return Response({"kind": "redirect", "location": redirect.link, "permanent": redirect.is_permanent})


class ResolvePageView(APIView):
    """GET ?path=/about/ → the live page at that path, else a redirect for it, else 404."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request) -> Response:
        path = request.query_params.get("path", "")
        if not (path.startswith("/") and path.endswith("/")) or "\0" in path:
            return Response({"detail": "path must start and end with /."}, status=status.HTTP_400_BAD_REQUEST)

        site = default_site()
        try:
            page = site.root_page.specific.route(request, [part for part in path.split("/") if part]).page
        except Http404:
            return redirect_response(site, path)

        # Private pages are out of scope: the storefront has no way to check a view restriction.
        if page.get_view_restrictions().exists():
            raise NotFound()
        return Response({"kind": "page", "page": page_payload(page, PAGE_FIELDS)})


class NavigationView(APIView):
    """GET → the site root URL and its live, public, in-menu children."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request) -> Response:
        return Response(navigation_payload(default_site()))
