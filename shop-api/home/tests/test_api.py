"""CMS content API. The views are called with APIRequestFactory; config/urls.py mounts them at api/cms/."""
import re
import shutil
import tempfile

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import include, path
from rest_framework import status
from rest_framework.test import APIRequestFactory
from wagtail import urls as wagtail_urls
from wagtail.contrib.redirects.models import Redirect
from wagtail.images.models import Image
from wagtail.images.tests.utils import get_test_image_file
from wagtail.models import Page, PageViewRestriction, Site

from home.models import HomePage, StandardPage
from home.views import NavigationView, ResolvePageView

# Wagtail builds page URLs by reversing its `wagtail_serve` route, which this test URLconf provides.
urlpatterns = [path("", include(wagtail_urls))]

factory = APIRequestFactory()


def resolve(page_path: str | None, **headers):
    params = {} if page_path is None else {"path": page_path}
    return ResolvePageView.as_view()(factory.get("/api/cms/pages/resolve/", params, **headers))


def navigation():
    return NavigationView.as_view()(factory.get("/api/cms/navigation/"))


@override_settings(ROOT_URLCONF=__name__)
class CmsApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.home = Page.get_first_root_node().add_child(
            instance=HomePage(title="Home", slug="shop-home", hero_title="Hello", intro="<p>Hi</p>", featured_count=3)
        )
        cls.site = Site.objects.get(is_default_site=True)
        cls.site.root_page = cls.home
        cls.site.save()

        cls.about = cls.home.add_child(
            instance=StandardPage(
                title="About",
                slug="about",
                body="<p>About us</p>",
                seo_title="About the shop",
                search_description="Who we are",
                show_in_menus=True,
            )
        )
        cls.team = cls.about.add_child(instance=StandardPage(title="Team", slug="team", show_in_menus=True))
        cls.draft = cls.home.add_child(instance=StandardPage(title="Draft", slug="draft", live=False, show_in_menus=True))
        cls.hidden = cls.home.add_child(instance=StandardPage(title="Hidden", slug="hidden"))
        cls.private = cls.home.add_child(instance=StandardPage(title="Private", slug="private", show_in_menus=True))
        cls.private.add_child(instance=StandardPage(title="Inner", slug="inner"))
        PageViewRestriction.objects.create(page=cls.private, restriction_type=PageViewRestriction.LOGIN)


class ResolvePageTests(CmsApiTestCase):
    def test_home_page_at_the_site_root(self):
        response = resolve("/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "kind": "page",
                "page": {
                    "id": self.home.pk,
                    "type": "home.HomePage",
                    "title": "Home",
                    "seo_title": "",
                    "search_description": "",
                    "url": "/",
                    "fields": {"hero_title": "Hello", "intro_html": "<p>Hi</p>", "featured_count": 3},
                },
            },
        )

    def test_standard_page(self):
        response = resolve("/about/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["page"],
            {
                "id": self.about.pk,
                "type": "home.StandardPage",
                "title": "About",
                "seo_title": "About the shop",
                "search_description": "Who we are",
                "url": "/about/",
                "fields": {"body_html": "<p>About us</p>"},
            },
        )

    def test_nested_page(self):
        response = resolve("/about/team/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual((response.data["page"]["id"], response.data["page"]["url"]), (self.team.pk, "/about/team/"))

    def test_draft_unknown_and_private_pages_are_not_found(self):
        for page_path in ("/draft/", "/missing/", "/about/missing/", "/private/", "/private/inner/"):
            with self.subTest(page_path):
                self.assertEqual(resolve(page_path).status_code, status.HTTP_404_NOT_FOUND)

    def test_path_must_start_and_end_with_a_slash(self):
        for page_path in (None, "", "about/", "/about"):
            with self.subTest(page_path):
                self.assertEqual(resolve(page_path).status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_invalid_token_is_rejected(self):
        response = resolve("/", HTTP_AUTHORIZATION="Token not-a-real-token")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class RedirectTests(CmsApiTestCase):
    def test_permanent_redirect_to_a_page(self):
        Redirect.add_redirect("/old-about/", self.about, is_permanent=True)

        response = resolve("/old-about/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"kind": "redirect", "location": "/about/", "permanent": True})

    def test_temporary_redirect_to_a_link(self):
        Redirect.add_redirect("/sale/", "https://example.com/sale/", is_permanent=False)

        response = resolve("/sale/")

        self.assertEqual(response.data, {"kind": "redirect", "location": "https://example.com/sale/", "permanent": False})

    def test_a_redirect_for_this_site_wins_over_one_for_all_sites(self):
        Redirect.add_redirect("/news/", "/everywhere/")
        Redirect.add_redirect("/news/", "/this-site/", site=self.site)

        self.assertEqual(resolve("/news/").data["location"], "/this-site/")

    def test_a_live_page_wins_over_a_redirect(self):
        Redirect.add_redirect("/about/", "/elsewhere/")

        self.assertEqual(resolve("/about/").data["kind"], "page")


class RichTextTests(CmsApiTestCase):
    def body_html(self, body: str) -> str:
        StandardPage.objects.filter(pk=self.about.pk).update(body=body)
        return resolve("/about/").data["page"]["fields"]["body_html"]

    def test_page_link_expands_to_a_relative_url(self):
        html = self.body_html(f'<p><a linktype="page" id="{self.team.pk}">Our team</a></p>')

        self.assertEqual(html, '<p><a href="/about/team/">Our team</a></p>')

    def test_image_embed_expands_to_an_absolute_media_url(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root)
        self.enterContext(override_settings(MEDIA_ROOT=media_root))
        image = Image.objects.create(title="Logo", file=get_test_image_file())

        html = self.body_html(f'<embed embedtype="image" id="{image.pk}" format="fullwidth" alt="Logo"/>')

        self.assertEqual(settings.MEDIA_URL, f"{settings.SHOP_API_PUBLIC_URL}/media/")
        src = re.search(r'src="([^"]+)"', html)
        self.assertIsNotNone(src)
        self.assertTrue(src.group(1).startswith(settings.MEDIA_URL), src.group(1))


class NavigationTests(CmsApiTestCase):
    def test_lists_only_live_public_in_menu_children_of_the_site_root(self):
        response = navigation()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"home_url": "/", "items": [{"id": self.about.pk, "title": "About", "url": "/about/"}]}
        )
