"""Put existing non-superuser staff in Wagtail's Moderators group, so they can edit and publish in the CMS.

From here on the User post_save handler in accounts.signals keeps the membership in step.
"""
from django.conf import settings
from django.db import migrations


def add_staff_to_moderators(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(settings.AUTH_USER_MODEL)
    group = Group.objects.filter(name="Moderators").first()
    if group is None:  # someone deleted or renamed Wagtail's default group
        return
    group.user_set.add(*User.objects.filter(is_staff=True, is_superuser=False))


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("wagtailcore", "0094_alter_page_locale"),
        ("wagtailadmin", "0005_editingsession_is_editing"),
    ]

    # Reversing leaves memberships alone: some may have been granted by hand since.
    operations = [migrations.RunPython(add_staff_to_moderators, migrations.RunPython.noop)]
