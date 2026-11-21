"""`{% versioned_static path %}`: a static URL that changes whenever the file does.

Browsers cache stylesheets heuristically, so after an edit they can keep serving
the old copy. Appending the file's modification time makes each edit a new URL.
"""

from os.path import getmtime

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def versioned_static(path: str) -> str:
    url = static(path)
    found = finders.find(path)
    if not isinstance(found, str):
        return url
    try:
        version = int(getmtime(found))
    except OSError:
        return url
    return f"{url}?v={version}"
