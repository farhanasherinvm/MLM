from rest_framework import permissions

class IsAdminOrReadOnly(permissions.BasePermission):
    
    def has_permission(self, request, view):
        # Allow read-only methods (GET, HEAD, OPTIONS) for authenticated users
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        # Allow write methods (POST, PUT, PATCH, DELETE) only for admin users
        return request.user and request.user.is_staff