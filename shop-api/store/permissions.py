from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsStaffOrReadOnly(BasePermission):
    """Anyone may read; only staff may create, change or delete."""

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)
