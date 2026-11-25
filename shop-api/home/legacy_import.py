"""Move the CMS content from a copy of shop-web's old database into this one.

Rows travel through Django's python serializer with natural foreign keys, so content types,
users and sites are matched by name rather than by id, while the primary keys of pages,
images and documents stay as they were: rich text links to them by id.

Each step takes its source alias, target alias, storage and output stream as arguments.
The target must be the default database: Wagtail's tree, page deletion, reference index
and search index code always work on it.
"""
import json
from collections import Counter
from collections.abc import Iterable
from io import TextIOBase
from itertools import chain
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import serializers
from django.core.files import File
from django.core.files.storage import Storage
from django.core.management import call_command
from django.core.management.color import no_style
from django.core.serializers.base import DeserializationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DEFAULT_DB_ALIAS, IntegrityError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Field, Model, QuerySet
from taggit.models import Tag, TaggedItem
from wagtail.contrib.redirects.models import Redirect
from wagtail.documents import get_document_model
from wagtail.images import get_image_model
from wagtail.models import (
    Collection,
    GroupApprovalTask,
    GroupCollectionPermission,
    GroupPagePermission,
    Locale,
    Page,
    PageLogEntry,
    Revision,
    Site,
    Task,
    Workflow,
    WorkflowPage,
    WorkflowTask,
    get_page_models,
)
from wagtail.utils.file import hash_filelike

from home.management.commands.bootstrap_site import site_address

# Created by Wagtail's migrations on both sides. Compared and reported, never copied.
COMPARED_MODELS = [
    Group,
    Locale,
    GroupPagePermission,
    GroupCollectionPermission,
    Workflow,
    Task,
    GroupApprovalTask,
    WorkflowTask,
    WorkflowPage,
]
# Caches and indexes Wagtail rebuilds, and transient editing state. Never copied.
REGENERATED_MODELS = {
    "wagtailimages.rendition",
    "wagtailcore.referenceindex",
    "wagtailsearch.indexentry",
    "wagtailsearch.sqliteftsindexentry",
    "wagtailembeds.embed",
    "wagtailadmin.editingsession",
    "wagtailcore.uploadedfile",
}
# Target content that --replace does not delete, because deleting a file row also deletes its file.
KEPT_ON_REPLACE = {"images", "documents", "collections", "tags", "tagged items"}

Row = dict  # one object in Django's python serialization format: {"model", "pk", "fields"}


class LegacyImportError(Exception):
    """The import cannot go ahead, or what it wrote does not match the source."""


def is_cms_app(app_label: str) -> bool:
    return app_label.startswith("wagtail") or app_label in ("home", "taggit")


def page_models() -> list[type[Page]]:
    """Concrete Page subclasses, whose own rows sit beside wagtailcore_page."""
    return [model for model in get_page_models() if model is not Page and not model._meta.proxy]


def media_models() -> list[type[Model]]:
    return [get_image_model(), get_document_model()]


def copied_querysets(alias: str) -> list[QuerySet]:
    """Every copied table on `alias`, ordered so each row's foreign keys load before it."""
    return [
        Collection.objects.using(alias).order_by("path"),
        Tag.objects.using(alias).order_by("pk"),
        Revision.objects.using(alias).order_by("pk"),
        Page.objects.using(alias).order_by("path"),
        *(model.objects.using(alias).order_by("pk") for model in page_models()),
        Site.objects.using(alias).order_by("pk"),
        PageLogEntry.objects.using(alias).order_by("pk"),
        *(model.objects.using(alias).order_by("pk") for model in media_models()),
        TaggedItem.objects.using(alias).order_by("pk"),
        Redirect.objects.using(alias).order_by("pk"),
    ]


def export_rows(object_lists: list[Iterable[Model]]) -> list[Row]:
    return [
        row
        for objects in object_lists
        for row in serializers.serialize("python", objects, use_natural_foreign_keys=True)
    ]


def require_source_file(connection: BaseDatabaseWrapper) -> None:
    """Refuse a missing sqlite file before anything connects: sqlite would create an empty one."""
    if connection.vendor != "sqlite" or connection.is_in_memory_db():
        return
    path = Path(connection.settings_dict["NAME"])
    if not path.is_file():
        raise LegacyImportError(f"The legacy CMS database {path} does not exist. Copy shop-web/db.sqlite3 there first.")


def check_migrations(source: str, target: str) -> None:
    """Both databases must have applied the same Wagtail, home and taggit migrations."""
    applied = [
        {key for key in MigrationRecorder(connections[alias]).applied_migrations() if is_cms_app(key[0])}
        for alias in (source, target)
    ]
    if applied[0] != applied[1]:
        raise LegacyImportError(
            "The CMS migrations differ. "
            f"Only in the source: {sorted(applied[0] - applied[1])}. "
            f"Only in the target: {sorted(applied[1] - applied[0])}."
        )


def check_shared_rows(source: str, target: str) -> None:
    """Rows the copied data points at by id, which both sides must hold identically."""
    for model in (Page, Collection):
        roots = [list(model.objects.using(alias).filter(depth=1).values_list("pk", "path")) for alias in (source, target)]
        if roots[0] != roots[1]:
            raise LegacyImportError(f"The {model._meta.verbose_name} tree roots differ: {roots[0]} != {roots[1]}.")
    locales = [dict(Locale.objects.using(alias).values_list("pk", "language_code")) for alias in (source, target)]
    if not locales[0].items() <= locales[1].items():
        raise LegacyImportError(f"The source locales {locales[0]} are not all in the target {locales[1]}.")


def check_unhandled(source: str, copied: list[QuerySet]) -> None:
    """Fail on source rows in a CMS table the import neither copies, compares nor regenerates."""
    handled = {queryset.model._meta.label_lower for queryset in copied}
    handled |= {model._meta.label_lower for model in COMPARED_MODELS} | REGENERATED_MODELS
    unhandled = {
        model._meta.label: count
        for model in apps.get_models()
        if is_cms_app(model._meta.app_label) and model._meta.managed and model._meta.label_lower not in handled
        if (count := model._base_manager.using(source).count())
    }
    if unhandled:
        raise LegacyImportError(f"The source has rows the import does not handle: {unhandled}.")


def signature(row: Row) -> str:
    """A row's content without its own id; many-to-many lists sorted."""
    fields = {name: sorted(value) if isinstance(value, list) else value for name, value in row["fields"].items()}
    return json.dumps([row["model"], fields], sort_keys=True, cls=DjangoJSONEncoder)


def report_shared_differences(source: str, target: str, out: TextIOBase) -> None:
    """Groups, permissions, workflows and locales stay as the target's migrations made them."""
    for model in COMPARED_MODELS:
        sides = [
            Counter(map(signature, export_rows([model.objects.using(alias).order_by("pk")])))
            for alias in (source, target)
        ]
        for row in sorted((sides[0] - sides[1]).elements()):
            out.write(f"Not copied, only in the source: {row}\n")
        for row in sorted((sides[1] - sides[0]).elements()):
            out.write(f"Kept, only in the target: {row}\n")


def related_fields(model: type[Model], related_model: type[Model]) -> list[Field]:
    return [field for field in model._meta.local_fields if field.is_relation and field.related_model is related_model]


def clear_missing_users(object_lists: list[list[Model]], source: str, out: TextIOBase) -> list[str]:
    """Clear user ids the source no longer holds, which log entries keep after a user is deleted.

    Serializing such a reference by natural key would fail, so the objects are changed in memory.
    """
    user_model = get_user_model()
    known = set(user_model._base_manager.using(source).values_list("pk", flat=True))
    cleared = []
    for obj in chain.from_iterable(object_lists):
        for field in related_fields(type(obj), user_model):
            user_id = getattr(obj, field.attname)
            if user_id is not None and user_id not in known:
                setattr(obj, field.attname, None)
                cleared.append(f"{obj._meta.label_lower} {obj.pk} {field.name} (was user id {user_id})")
    for entry in cleared:
        out.write(f"No such user in the source, cleared: {entry}\n")
    return cleared


def remap_users(rows: list[Row], target: str, out: TextIOBase) -> list[str]:
    """Keep each user reference whose username exists in the target, and clear the rest."""
    user_model = get_user_model()
    usernames = set(user_model.objects.using(target).values_list(user_model.USERNAME_FIELD, flat=True))
    cleared = []
    for row in rows:
        for field in related_fields(apps.get_model(row["model"]), user_model):
            if row["fields"][field.name] is None:
                continue
            (username,) = row["fields"][field.name]
            if username not in usernames:
                row["fields"][field.name] = None
                cleared.append(f"{row['model']} {row['pk']} {field.name} (was {username!r})")
    for entry in cleared:
        out.write(f"No such user here, cleared: {entry}\n")
    return cleared


def rewrite_site(rows: list[Row], site_url: str, out: TextIOBase) -> None:
    """Point the default Site, and every reference to it, at the storefront's host and port."""
    defaults = [row for row in rows if row["model"] == "wagtailcore.site" and row["fields"]["is_default_site"]]
    if len(defaults) != 1:
        raise LegacyImportError(f"The source needs exactly one default Site; it has {len(defaults)}.")
    fields = defaults[0]["fields"]
    old, new = (fields["hostname"], fields["port"]), site_address(site_url)
    for row in rows:
        for field in related_fields(apps.get_model(row["model"]), Site):
            if row["fields"][field.name] is not None and tuple(row["fields"][field.name]) == old:
                row["fields"][field.name] = new
    fields["hostname"], fields["port"] = new
    out.write(f"Default site {old[0]}:{old[1]} becomes {new[0]}:{new[1]}.\n")


def target_content(target: str) -> dict[str, int]:
    """What the target holds beyond Root and Wagtail's placeholder page, by kind."""
    page_type = Page.objects.using(target).filter(depth=1).values("content_type")
    placeholders = Page.objects.using(target).filter(depth=2, numchild=0, content_type__in=page_type)
    counts = {
        "pages": Page.objects.using(target).filter(depth__gt=1).exclude(pk__in=placeholders).count(),
        "revisions": Revision.objects.using(target).count(),
        "page log entries": PageLogEntry.objects.using(target).count(),
        "redirects": Redirect.objects.using(target).count(),
        "images": get_image_model().objects.using(target).count(),
        "documents": get_document_model().objects.using(target).count(),
        "collections": Collection.objects.using(target).filter(depth__gt=1).count(),
        "tags": Tag.objects.using(target).count(),
        "tagged items": TaggedItem.objects.using(target).count(),
    }
    return {kind: count for kind, count in counts.items() if count}


def clear_target(target: str, replace: bool, out: TextIOBase) -> None:
    """Delete the placeholder page, or with `replace` every page but Root, and their sites and history."""
    content = target_content(target)
    if content and not replace:
        raise LegacyImportError(f"The target already holds CMS content {content}. Run again with --replace to delete it.")
    kept = {kind: count for kind, count in content.items() if kind in KEPT_ON_REPLACE}
    if kept:
        raise LegacyImportError(f"--replace does not delete {kept}. Delete them in the CMS first.")
    for page in Page.objects.using(target).filter(depth=2):
        out.write(f"Deleting target page {page.pk} {page.url_path} and everything below it.\n")
        page.delete()
    # Deleting a page logs it, so the history goes after the pages.
    for queryset in (Site, Revision, PageLogEntry, Redirect):
        queryset.objects.using(target).all().delete()


def load_rows(rows: list[Row], target: str) -> None:
    """Save every row as it is, the way loaddata does, then bring the id sequences past it."""
    deferred = []
    try:
        for obj in serializers.deserialize("python", rows, using=target, handle_forward_references=True):
            obj.save(using=target)
            if obj.deferred_fields:
                deferred.append(obj)
        for obj in deferred:
            obj.save_deferred_fields(using=target)
    except (DeserializationError, IntegrityError) as error:
        raise LegacyImportError(f"Loading the rows failed: {error}") from error
    connection = connections[target]
    models = [queryset.model for queryset in copied_querysets(target)]
    with connection.cursor() as cursor:
        for sql in connection.ops.sequence_reset_sql(no_style(), models):
            cursor.execute(sql)


def media_names(rows: list[Row]) -> list[str]:
    labels = {model._meta.label_lower for model in media_models()}
    return [row["fields"]["file"] for row in rows if row["model"] in labels]


def file_hash(storage: Storage, name: str) -> str:
    with storage.open(name, "rb") as handle:
        return hash_filelike(handle)


def copy_media(rows: list[Row], media_source: Path, storage: Storage, saved: list[str], out: TextIOBase) -> None:
    """Copy each image and document file under its own name and check it against its recorded hash.

    Each name it stores is appended to `saved` straight away, so a rollback can remove the file again.
    """
    labels = {model._meta.label_lower for model in media_models()}
    for row in (row for row in rows if row["model"] in labels):
        name, recorded = row["fields"]["file"], row["fields"]["file_hash"]
        path = media_source / name
        if not path.is_file():
            raise LegacyImportError(f"{row['model']} {row['pk']}: the file {path} is missing.")
        with path.open("rb") as handle:
            digest = hash_filelike(handle)
        if recorded and digest != recorded:
            raise LegacyImportError(f"{row['model']} {row['pk']}: {path} does not match its recorded hash.")
        if storage.exists(name):
            if file_hash(storage, name) != digest:
                raise LegacyImportError(f"{row['model']} {row['pk']}: a different file is already stored as {name}.")
            out.write(f"Already in place: {name}\n")
            continue
        with path.open("rb") as handle:
            stored = storage.save(name, File(handle))
        saved.append(stored)
        if stored != name or file_hash(storage, stored) != digest:
            raise LegacyImportError(f"{row['model']} {row['pk']}: copying {name} did not reproduce the file.")
        out.write(f"Copied {name}\n")


def verify(rows: list[Row], target: str, storage: Storage, out: TextIOBase) -> list[str]:
    """Compare the target with the rows meant for it. Returns one line per problem."""
    copied = copied_querysets(target)
    expected = Counter(row["model"] for row in rows)
    problems = []
    for queryset in copied:
        label, count = queryset.model._meta.label_lower, queryset.count()
        out.write(f"{label}: {count} in the target, {expected[label]} from the source\n")
        if count != expected[label]:
            problems.append(f"{label}: {count} rows, expected {expected[label]}")
    written = {(row["model"], row["pk"]): row["fields"] for row in export_rows(copied)}
    problems += [
        f"{row['model']} {row['pk']} differs from the source"
        for row in rows
        if written.get((row["model"], row["pk"])) != row["fields"]
    ]
    for model in (Page, Collection):
        if any(model.find_problems()):
            problems.append(f"The {model._meta.verbose_name} tree has problems: {model.find_problems()}")
    try:
        connections[target].check_constraints(table_names=[queryset.model._meta.db_table for queryset in copied])
    except IntegrityError as error:
        problems.append(f"Broken foreign key: {error}")
    problems += [f"Missing file {name}" for name in media_names(rows) if not storage.exists(name)]
    return problems


def import_legacy_cms(
    *,
    source: str,
    target: str,
    storage: Storage,
    media_source: Path,
    site_url: str,
    replace: bool,
    dry_run: bool,
    out: TextIOBase,
) -> None:
    """Check, copy, verify and index in one transaction on the target; `dry_run` rolls it back.

    Files copied into `storage` are deleted again whenever the transaction does not commit.
    """
    if target != DEFAULT_DB_ALIAS:
        raise LegacyImportError(f"The target must be the {DEFAULT_DB_ALIAS!r} database, not {target!r}.")
    if source == target:
        raise LegacyImportError("The source and the target are the same database.")
    require_source_file(connections[source])
    check_migrations(source, target)
    check_shared_rows(source, target)
    copied = copied_querysets(source)
    check_unhandled(source, copied)
    report_shared_differences(source, target, out)

    objects = [list(queryset) for queryset in copied]
    clear_missing_users(objects, source, out)
    rows = export_rows(objects)
    remap_users(rows, target, out)
    rewrite_site(rows, site_url, out)
    saved_files: list[str] = []
    committed = False
    try:
        with transaction.atomic(using=target):
            clear_target(target, replace, out)
            load_rows(rows, target)
            copy_media(rows, media_source, storage, saved_files, out)
            problems = verify(rows, target, storage, out)
            if problems:
                raise LegacyImportError("Verification failed, nothing was written:\n" + "\n".join(problems))
            call_command("rebuild_references_index", stdout=out)
            call_command("update_index", stdout=out)
            if dry_run:
                transaction.set_rollback(True, using=target)
        committed = not dry_run
    finally:
        if not committed:
            for name in saved_files:
                storage.delete(name)
                out.write(f"Removed the copied file {name}\n")
    out.write("Dry run: rolled back, nothing was written.\n" if dry_run else f"Imported {len(rows)} rows.\n")
