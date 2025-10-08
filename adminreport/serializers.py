from rest_framework import serializers
from django.core.exceptions import ObjectDoesNotExist
# Consolidated Model Imports (ensure these models are accessible)
from level.models import UserLevel, LevelPayment, Level
from users.models import CustomUser 
from .models import AdminNotification # Included for the Notification serializer

class AdminSendRequestReportSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()
    from_name = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    linked_username = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    requested_date = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['id', 'from_user', 'username', 'from_name', 'amount', 'status', 'requested_date', 'payment_method', 'level','linked_username']

    def get_from_user(self, obj):
        user = getattr(obj, 'user', None)
        return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() if user else 'N/A'

    def get_from_name(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip() or linked_user_id
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_username(self, obj):
        user = getattr(obj, 'user', None)
        return getattr(user, 'user_id', 'N/A') if user else 'N/A'

    def get_amount(self, obj):
        return getattr(obj.level, 'amount', 0) if obj.level else 0

    def get_status(self, obj):
        return "Completed" if getattr(obj, 'status', '') == 'paid' else "Pending"

    def get_requested_date(self, obj):
        requested_date = getattr(obj, 'requested_date', None)
        return requested_date.strftime("%Y-%m-%d %H:%M:%S") if requested_date else None

    def get_payment_method(self, obj):
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        if latest_payment:
            method = latest_payment.payment_method
            if method == 'Manual' and hasattr(latest_payment, 'payment_proof') and latest_payment.payment_proof:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(latest_payment.payment_proof.url)
            return method
        return 'N/A'

    def get_linked_username(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', linked_user_id)
            except ObjectDoesNotExist:
                return linked_user_id
        return 'N/A'

    def get_level(self, obj):
        return getattr(obj.level, 'name', 'N/A') if obj.level else 'N/A'
    
    def to_representation(self, instance):
        representation = super().to_representation(instance)
        for field in self.fields:
            if representation.get(field) in (None, ''):
                representation[field] = 0 if field == 'amount' else None if field == 'requested_date' else 'N/A'
        return representation


class AdminPaymentSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    linked_username = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    gic = serializers.SerializerMethodField()
    status = serializers.CharField()
    payment_method = serializers.CharField()
    created_at = serializers.DateTimeField()
    
    class Meta:
        model = LevelPayment
        fields = ['id', 'from_user', 'username', 'linked_username', 'level', 'amount', 'gic', 'status', 'payment_method', 'created_at']

    def get_gic(self, obj):
        amount = getattr(obj, 'amount', 0)
        return float(amount) * 0.18

    def get_from_user(self, obj):
        user = getattr(obj.user_level, 'user', None) if getattr(obj, 'user_level', None) else None
        return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() if user else 'N/A'

    def get_username(self, obj):
        user = getattr(obj.user_level, 'user', None) if getattr(obj, 'user_level', None) else None
        return getattr(user, 'user_id', 'N/A') if user else 'N/A'

    def get_linked_username(self, obj):
        linked_user_id = getattr(obj.user_level, 'linked_user_id', None) if getattr(obj, 'user_level', None) else None
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', linked_user_id)
            except ObjectDoesNotExist:
                return linked_user_id
        return 'N/A'

    def get_level(self, obj):
        level = getattr(obj.user_level, 'level', None) if getattr(obj, 'user_level', None) else None
        return getattr(level, 'name', 'N/A') if level else 'N/A'
    
# AUCReportSerializer (Provided by User - Retained as is)
class AUCReportSerializer(serializers.Serializer):
    from_user = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    from_name = serializers.SerializerMethodField()
    linked_username = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    gic = serializers.SerializerMethodField()

    def _get_linked_user(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        
        if not hasattr(self, '_linked_user_cache'):
            self._linked_user_cache = {}
            
        if linked_user_id not in self._linked_user_cache:
            linked_user = None
            if linked_user_id:
                try:
                    linked_user = CustomUser.objects.get(user_id=linked_user_id)
                except CustomUser.DoesNotExist:
                    pass
            self._linked_user_cache[linked_user_id] = linked_user
            
        return self._linked_user_cache.get(linked_user_id)

    def get_from_user(self, obj):
        return f"{obj.user.last_name or ''}, {obj.user.first_name or ''}".strip() if hasattr(obj, 'user') and obj.user else ''

    def get_username(self, obj):
        return obj.user.user_id if hasattr(obj, 'user') and obj.user else ''

    def get_from_name(self, obj):
        linked_user = self._get_linked_user(obj)
        if linked_user:
            return f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()

    def get_linked_username(self, obj):
        return getattr(obj, 'linked_user_id', '')

    def get_amount(self, obj):
        if hasattr(obj, 'amount') and obj.amount:
            return obj.amount
            
        if hasattr(obj, 'received') and obj.received:
            return obj.received
            
        if hasattr(obj, 'level') and hasattr(obj.level, 'amount'):
            return obj.level.amount
            
        return 0

    def get_status(self, obj):
        return obj.status if hasattr(obj, 'status') else ''

    def get_date(self, obj):
        if isinstance(obj, LevelPayment):
            return obj.created_at
        elif isinstance(obj, UserLevel):
            return obj.approved_at or obj.requested_date
        return None

    def get_payment_method(self, obj):
        if isinstance(obj, LevelPayment):
            return obj.payment_method
        elif isinstance(obj, UserLevel):
            return obj.payment_mode
        
        return ''

    def get_gic(self, obj):
        base_amount = 0

        if isinstance(obj, LevelPayment):
            base_amount = getattr(obj, 'amount', 0)
        
        elif isinstance(obj, UserLevel):
            base_amount = getattr(obj, 'received', 0)
            
            if base_amount is None or base_amount == 0:
                if hasattr(obj, 'level') and hasattr(obj.level, 'amount'):
                    base_amount = getattr(obj.level, 'amount', 0)
        
        try:
            return float(base_amount) * 0.18
        except (TypeError, ValueError):
            return 0

class AdminNotificationSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.user_id', read_only=True) 

    class Meta:
        model = AdminNotification
        fields = ['id', 'username', 'operation_type', 'description', 'amount', 'gic', 'timestamp', 'is_read']


# class AdminNotificationsSerializer(serializers.Serializer):
#     notifications = AdminNotificationSerializer(many=True)
class AdminSummaryAnalyticsSerializer(serializers.Serializer):
    total_registered_users = serializers.IntegerField()
    total_active_users = serializers.IntegerField()
    total_revenue_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_gic_collected = serializers.DecimalField(max_digits=12, decimal_places=2) # Re-added GIC
    Completed_users_by_level = serializers.DictField()

class UserAnalyticsSerializer(serializers.Serializer):
    user_id = serializers.CharField(max_length=50)
    full_name = serializers.CharField(max_length=255)
    total_income_generated = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_referrals = serializers.IntegerField()
    levels_completed = serializers.IntegerField() 
    total_payments_made = serializers.DecimalField(max_digits=12, decimal_places=2)
    