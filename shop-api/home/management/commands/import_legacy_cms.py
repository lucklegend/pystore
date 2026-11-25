from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS

from home.legacy_import import LegacyImportError, import_legacy_cms


class Command(BaseCommand):
    help = (
        "Copy the CMS pages, revisions, history, media and redirects from a copy of shop-web's old "
        "database into this one, then verify them. Fails, writing nothing, on any mismatch."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Run every step and check, then roll back.")
        parser.add_argument(
            "--replace", action="store_true", help="Delete the CMS pages this database already has before importing."
        )
        parser.add_argument(
            "--media-source",
            type=Path,
            default=settings.BASE_DIR.parent / "shop-web" / "media",
            help="shop-web's MEDIA_ROOT, where the image and document files are read from.",
        )
        parser.add_argument(
            "--site-url",
            default=settings.STOREFRONT_URL,
            help="The storefront URL the default Site is pointed at. Defaults to STOREFRONT_URL.",
        )
        parser.add_argument(
            "--database", default="legacy_cms", help="The database alias to read the old CMS from."
        )

    def handle(self, *args, **options) -> None:
        try:
            import_legacy_cms(
                source=options["database"],
                target=DEFAULT_DB_ALIAS,
                storage=default_storage,
                media_source=options["media_source"],
                site_url=options["site_url"],
                replace=options["replace"],
                dry_run=options["dry_run"],
                out=self.stdout,
            )
        except LegacyImportError as error:
            raise CommandError(str(error)) from error
