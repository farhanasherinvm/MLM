from rest_framework.permissions import BasePermission

class IsProjectAdmin(BasePermission):
    """
    Allows access only to project admins (is_admin_user=True)
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and getattr(request.user, "is_admin_user", False)
