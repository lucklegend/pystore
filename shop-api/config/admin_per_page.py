"""Lets staff choose how many rows an admin list shows, with ?per_page=10|20|50|100."""
from django.contrib.admin.views.main import PAGE_VAR, ChangeList
from django.http import HttpRequest

PER_PAGE_VAR = "per_page"
PER_PAGE_CHOICES = (10, 20, 50, 100)
DEFAULT_PER_PAGE = PER_PAGE_CHOICES[0]


def requested_per_page(request: HttpRequest) -> int:
    """The page size asked for in the query string, or the default if it's missing or not offered."""
    offered = {str(size): size for size in PER_PAGE_CHOICES}
    return offered.get(request.GET.get(PER_PAGE_VAR, ""), DEFAULT_PER_PAGE)


class PerPageChangeList(ChangeList):
    def get_filters_params(self, params=None):
        # per_page isn't a model field; without this the admin rejects it as a bad filter.
        lookup_params = super().get_filters_params(params)
        lookup_params.pop(PER_PAGE_VAR, None)
        return lookup_params

    def get_results(self, request):
        self.list_per_page = requested_per_page(request)
        super().get_results(request)

    def per_page_options(self) -> list[dict]:
        """One dropdown option per page size; each URL keeps the current search, filters and sort, and returns to page 1."""
        return [
            {
                "size": size,
                "url": self.get_query_string({PER_PAGE_VAR: size}, remove=[PAGE_VAR]),
                "current": size == self.list_per_page,
            }
            for size in PER_PAGE_CHOICES
        ]


def per_page_changelist(request: HttpRequest, **kwargs) -> type[ChangeList]:
    return PerPageChangeList
