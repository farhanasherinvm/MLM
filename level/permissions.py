from rest_framework import permissions
from .models import LevelPayment

class IsAdminOrReadOnly(permissions.BasePermission):
    
    def has_permission(self, request, view):
        # Allow read-only methods (GET, HEAD, OPTIONS) for authenticated users
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        # Allow write methods (POST, PUT, PATCH, DELETE) only for admin users
        return request.user and request.user.is_staff


class IsPaymentRecipient(permissions.BasePermission):
   
    message = "You are not the designated recipient (linked user) for this payment."

    def has_permission(self, request, view):
        # Allow access to the list endpoint
        if view.action == 'list':
            return request.user and request.user.is_authenticated
        
        # For actions (accept/reject), we check object permission in has_object_permission
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # obj here is the LevelPayment instance
        # Check if the current user's ID matches the linked_user_id on the related UserLevel
        return str(request.user.user_id) == str(obj.user_level.linked_user_id)