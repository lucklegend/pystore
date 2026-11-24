from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from wagtail.models import Page, Site

from home.management.commands.bootstrap_site import site_address
from home.models import HomePage, StandardPage


def bootstrap() -> str:
    out = StringIO()
    call_command("bootstrap_site", stdout=out)
    return out.getvalue()


class BootstrapSiteTests(TestCase):
    @override_settings(STOREFRONT_URL="http://shop.example.com:8080")
    def test_replaces_the_placeholder_and_points_the_site_at_the_storefront(self):
        bootstrap()

        home = HomePage.objects.get()
        self.assertEqual(home.get_parent().specific_class, Page)  # directly under Root
        self.assertEqual([child.specific_class for child in Page.get_first_root_node().get_children()], [HomePage])
        self.assertEqual(StandardPage.objects.get().get_parent().pk, home.pk)
        site = Site.objects.get()
        self.assertEqual((site.hostname, site.port, site.root_page_id), ("shop.example.com", 8080, home.pk))
        self.assertTrue(site.is_default_site)

    def test_running_twice_changes_nothing(self):
        bootstrap()

        output = bootstrap()

        self.assertIn("nothing to do", output)
        self.assertEqual(HomePage.objects.count(), 1)
        self.assertEqual(StandardPage.objects.count(), 1)
        self.assertEqual(Site.objects.count(), 1)


class SiteAddressTests(SimpleTestCase):
    def test_uses_the_scheme_default_port_when_none_is_given(self):
        self.assertEqual(site_address("https://shop.example.com"), ("shop.example.com", 443))
        self.assertEqual(site_address("http://shop.example.com/"), ("shop.example.com", 80))

    def test_keeps_an_explicit_port(self):
        self.assertEqual(site_address("http://127.0.0.1:8080"), ("127.0.0.1", 8080))


class PreviewTests(SimpleTestCase):
    def test_page_types_offer_no_preview(self):
        for model in (HomePage, StandardPage):
            with self.subTest(model.__name__):
                self.assertEqual(model().preview_modes, [])
                self.assertFalse(model().is_previewable())
