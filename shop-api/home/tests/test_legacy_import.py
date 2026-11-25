from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder
from django.test import SimpleTestCase, TestCase, override_settings
from taggit.models import TaggedItem
from wagtail.contrib.redirects.models import Redirect
from wagtail.documents import get_document_model
from wagtail.images import get_image_model
from wagtail.models import Collection, Page, PageLogEntry, PageViewRestriction, Revision, Site
from wagtail.utils.file import hash_filelike

from home.legacy_import import LegacyImportError, require_source_file
from home.models import HomePage, StandardPage
from store.tests.factories import make_user

SOURCE = "legacy_cms"
FIXTURE = Path(__file__).with_name("legacy_cms.json")
# The files behind the fixture's image and document; their SHA-1s are the fixture's file_hash values.
FILES = {"original_images/logo.png": b"legacy logo bytes", "documents/terms.txt": b"legacy terms of sale"}
STOREFRONT = "https://shop.example.com"


def seed_source() -> None:
    """Give the source the target's migration history, content-type ids of its own, and the fixture's content."""
    recorder = MigrationRecorder(connections[SOURCE])
    for app_label, name in MigrationRecorder(connections["default"]).applied_migrations():
        recorder.record_applied(app_label, name)
    ContentType.objects.using(SOURCE).filter(app_label="home").delete()
    for model in ("homepage", "standardpage"):
        ContentType.objects.db_manager(SOURCE).create(app_label="home", model=model)
    ContentType.objects.clear_cache()
    call_command("loaddata", FIXTURE, database=SOURCE, verbosity=0)


class ImportLegacyCmsTests(TestCase):
    databases = {"default", SOURCE}

    @classmethod
    def setUpClass(cls):
        # The source test database is built from the models rather than migrated, because Wagtail's data
        # migrations only write to the default database. So it has no migration table yet, and sqlite
        # cannot create one inside the test transaction.
        MigrationRecorder(connections[SOURCE]).ensure_schema()
        super().setUpClass()

    def setUp(self):
        self.addCleanup(ContentType.objects.clear_cache)
        seed_source()
        self.editor = make_user("editor")
        self.media_source = self.temp_dir()
        for name, content in FILES.items():
            path = self.media_source / name
            path.parent.mkdir(parents=True)
            path.write_bytes(content)
        self.media_root = self.temp_dir()
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root))

    def temp_dir(self) -> Path:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def run_import(self, *args: str) -> str:
        out = StringIO()
        call_command(
            "import_legacy_cms", "--media-source", str(self.media_source), "--site-url", STOREFRONT, *args, stdout=out
        )
        return out.getvalue()

    def stored_files(self) -> list[str]:
        return sorted(path.relative_to(self.media_root).as_posix() for path in self.media_root.rglob("*") if path.is_file())

    def assert_target_untouched(self):
        self.assertEqual(list(Page.objects.values_list("pk", "path")), [(1, "0001"), (2, "00010001")])
        self.assertFalse(HomePage.objects.exists())
        self.assertEqual(list(Site.objects.values_list("pk", flat=True)), [1])
        self.assertEqual(self.stored_files(), [])

    def test_preserves_primary_keys_paths_and_content(self):
        self.run_import()

        self.assertEqual(
            list(Page.objects.order_by("path").values_list("pk", "path", "url_path", "title")),
            [(1, "0001", "/", "Root"), (3, "00010001", "/home/", "Home"), (4, "000100010001", "/home/about/", "About")],
        )
        home = HomePage.objects.get(pk=3)
        self.assertEqual((home.hero_title, home.featured_count), ("Hello from the old CMS", 3))
        self.assertIn('<a linktype="page" id="4">about us</a>', home.intro)
        self.assertIn('<a linktype="document" id="1">', StandardPage.objects.get(pk=4).body)
        self.assertEqual(home.get_children().get().specific_class, StandardPage)
        self.assertEqual(Collection.objects.get(pk=2).get_parent().pk, 1)
        self.assertEqual(get_image_model().objects.get(pk=1).collection_id, 2)
        self.assertEqual(TaggedItem.objects.get().content_object, get_image_model().objects.get(pk=1))

    def test_remaps_content_types_by_natural_key(self):
        source_id = ContentType.objects.db_manager(SOURCE).get_by_natural_key("home", "homepage").pk
        target_type = ContentType.objects.get_for_model(HomePage)
        self.assertNotEqual(source_id, target_type.pk)

        self.run_import()

        self.assertEqual(Page.objects.get(pk=3).content_type, target_type)
        self.assertEqual(Page.objects.get(pk=4).specific_class, StandardPage)
        revision = Revision.objects.get()
        self.assertEqual(revision.content_type, target_type)
        self.assertEqual(Page.objects.get(pk=3).latest_revision, revision)
        self.assertIsInstance(revision.as_object(), HomePage)
        self.assertEqual(PageLogEntry.objects.get(pk=2).content_type, ContentType.objects.get_for_model(StandardPage))

    def test_replaces_the_placeholder_and_points_the_site_at_the_storefront(self):
        self.run_import()

        self.assertFalse(Page.objects.filter(pk=2).exists())
        site = Site.objects.get()
        self.assertEqual((site.pk, site.hostname, site.port, site.root_page_id), (2, "shop.example.com", 443, 3))
        self.assertTrue(site.is_default_site)
        self.assertEqual(Redirect.objects.get().site, site)

    def test_maps_users_by_username_and_clears_the_rest(self):
        output = self.run_import()

        self.assertNotEqual(self.editor.pk, 5)  # the editor's id in the source
        self.assertEqual(Page.objects.get(pk=3).owner, self.editor)
        self.assertEqual(Revision.objects.get().user, self.editor)
        self.assertEqual(PageLogEntry.objects.get(pk=2).user, self.editor)
        self.assertEqual(get_image_model().objects.get().uploaded_by_user, self.editor)
        self.assertIsNone(PageLogEntry.objects.get(pk=1).user_id)
        self.assertIn("No such user in the source, cleared: wagtailcore.pagelogentry 1 user (was user id 99)", output)
        self.assertIsNone(get_document_model().objects.get().uploaded_by_user)
        self.assertIn("No such user here, cleared: wagtaildocs.document 1 uploaded_by_user (was 'ghost')", output)

    def test_copies_the_files_and_checks_their_hashes(self):
        output = self.run_import()

        self.assertEqual(self.stored_files(), sorted(FILES))
        for model in (get_image_model(), get_document_model()):
            obj = model.objects.get()
            with default_storage.open(obj.file.name, "rb") as handle:
                self.assertEqual(hash_filelike(handle), obj.file_hash)
        self.assertIn("Copied original_images/logo.png", output)

    def test_leaves_the_trees_consistent(self):
        self.run_import()

        for model in (Page, Collection):
            with self.subTest(model.__name__):
                self.assertEqual(model.find_problems(), ([], [], [], [], []))

    def test_a_missing_file_fails_and_writes_nothing(self):
        (self.media_source / "documents/terms.txt").unlink()

        with self.assertRaisesMessage(CommandError, "terms.txt is missing"):
            self.run_import()

        self.assert_target_untouched()  # the image copied before the failure is removed again

    def test_a_file_that_does_not_match_its_hash_fails(self):
        (self.media_source / "original_images/logo.png").write_bytes(b"tampered")

        with self.assertRaisesMessage(CommandError, "does not match its recorded hash"):
            self.run_import()

        self.assert_target_untouched()

    def test_dry_run_writes_nothing(self):
        output = self.run_import("--dry-run")

        self.assertIn("Dry run: rolled back, nothing was written.", output)
        self.assert_target_untouched()

    def test_a_second_run_refuses_without_replace(self):
        self.run_import()

        with self.assertRaisesMessage(CommandError, "Run again with --replace"):
            self.run_import()

        self.assertEqual(HomePage.objects.count(), 1)

    def test_replace_refuses_to_delete_files(self):
        self.run_import()

        with self.assertRaisesMessage(CommandError, "--replace does not delete"):
            self.run_import("--replace")

        self.assertEqual(self.stored_files(), sorted(FILES))

    def test_replace_deletes_the_existing_pages(self):
        call_command("bootstrap_site", stdout=StringIO())
        with self.assertRaisesMessage(CommandError, "Run again with --replace"):
            self.run_import()

        self.run_import("--replace")

        self.assertEqual(HomePage.objects.get().hero_title, "Hello from the old CMS")
        self.assertEqual(list(Page.objects.order_by("path").values_list("pk", flat=True)), [1, 3, 4])
        self.assertEqual(Site.objects.get().root_page_id, 3)

    def test_a_migration_mismatch_aborts(self):
        MigrationRecorder(connections[SOURCE]).record_unapplied("home", "0001_initial")

        with self.assertRaisesMessage(CommandError, "Only in the target: [('home', '0001_initial')]"):
            self.run_import()

        self.assert_target_untouched()

    def test_a_private_page_aborts_rather_than_going_public(self):
        # bulk_create, because PageViewRestriction.save() looks its page up on the default database.
        PageViewRestriction.objects.using(SOURCE).bulk_create(
            [PageViewRestriction(page_id=4, restriction_type=PageViewRestriction.LOGIN)]
        )

        with self.assertRaisesMessage(CommandError, "rows the import does not handle: {'wagtailcore.PageViewRestriction': 1}"):
            self.run_import()

        self.assert_target_untouched()


class RequireSourceFileTests(SimpleTestCase):
    def sqlite_connection(self, name: Path) -> SimpleNamespace:
        return SimpleNamespace(vendor="sqlite", is_in_memory_db=lambda: False, settings_dict={"NAME": name})

    def test_refuses_a_missing_file_without_creating_it(self):
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "legacy_cms.sqlite3"

            with self.assertRaisesMessage(LegacyImportError, "does not exist"):
                require_source_file(self.sqlite_connection(missing))

            self.assertFalse(missing.exists())

    def test_accepts_an_existing_file(self):
        with TemporaryDirectory() as directory:
            present = Path(directory) / "legacy_cms.sqlite3"
            present.touch()

            require_source_file(self.sqlite_connection(present))
