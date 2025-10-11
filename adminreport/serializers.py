from rest_framework import serializers
from django.core.exceptions import ObjectDoesNotExist
# Consolidated Model Imports (ensure these models are accessible)
from level.models import UserLevel, LevelPayment, Level
from users.models import CustomUser 
from .models import AdminNotification # Included for the Notification serializer
from django.utils import timezone
from decimal import Decimal

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
    
class AUCReportSerializer(serializers.Serializer):
    """
    Serializer to unify data from Payment (Registration) and PmfPayment models, 
    and calculate GST for AUC report.
    """
    # User Details
    user_id = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    
    # Payment Details
    transaction_type = serializers.SerializerMethodField() # Registration, PMF Part 1, PMF Part 2
    amount = serializers.DecimalField(max_digits=10, decimal_places=2) 
    
    # GST Breakdown
    gst_total = serializers.SerializerMethodField()
    cgst = serializers.SerializerMethodField()
    sgst = serializers.SerializerMethodField()
    
    # Standard Fields
    status = serializers.CharField()
    date = serializers.SerializerMethodField()
    


    def _get_user(self, obj):
        
        # 1. Try direct ForeignKey link 
        if hasattr(obj, 'user') and obj.user_id and obj.user:
            return obj.user
        
        # 2. Fallback for Payment (Registration Fee) model
        if obj.__class__.__name__ == 'Payment':
            payment_user_id = getattr(obj, 'user_id', None)
            
            if payment_user_id:
                try:
                    # ✅ DIRECT FIX: Use the model to query the database
                    from your_app.models import CustomUser # OPTIONAL: Import here if preferred
                    return CustomUser.objects.get(user_id=payment_user_id)  
                except CustomUser.DoesNotExist:
                    pass
                except Exception:
                    # Catch all other exceptions (like database errors)
                    pass
        return None
    

    # --- Field Getters ---
    
    def get_user_id(self, obj):
        user = self._get_user(obj)
        return user.user_id if user else 'N/A'

    def get_user_name(self, obj):
        user = self._get_user(obj)
        if user:
            return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
        return 'N/A'

    def get_phone_number(self, obj):
        user = self._get_user(obj)
        return getattr(user, 'mobile', 'N/A')

    def get_email(self, obj):
        user = self._get_user(obj)
        return getattr(user, 'email', 'N/A')

    def get_transaction_type(self, obj):
        if obj.__class__.__name__ == 'Payment':
            # Payment model is for the initial 100 registration fee
            return 'Registration Fee'
        elif obj.__class__.__name__ == 'PmfPayment':
            # PmfPayment model is for PMF fees
            # This calls the method on the PmfPayment model (e.g., "PMF Part 1 Fee")
            return obj.get_pmf_type_display() 
        return 'Unknown'

    def get_date(self, obj):
        if hasattr(obj, 'created_at'):
            return timezone.localtime(obj.created_at).strftime("%Y-%m-%d %H:%M:%S")
        return None

    # --- GST Getters (Assuming 18% total GST) ---
    def _calculate_gst(self, obj):
        base_amount = getattr(obj, 'amount', Decimal('0.00'))
        
        try:
            base_amount = Decimal(base_amount)
        except (TypeError, ValueError):
            return Decimal('0.00'), Decimal('0.00')
        
        if base_amount == 0:
            return Decimal('0.00'), Decimal('0.00')

        # Calculation assuming 'amount' is the gross amount (Amount + GST)
        gst_rate = Decimal('0.18')
        # Total GST = (Gross Amount * GST Rate) / (1 + GST Rate)
        total_gst = (base_amount * gst_rate) / (Decimal('1.00') + gst_rate)
        half_gst = total_gst / Decimal('2.0')
        
        return total_gst.quantize(Decimal('0.01')), half_gst.quantize(Decimal('0.01'))

    def get_gst_total(self, obj):
        total_gst, _ = self._calculate_gst(obj)
        return total_gst

    def get_cgst(self, obj):
        _, half_gst = self._calculate_gst(obj)
        return half_gst

    def get_sgst(self, obj):
        _, half_gst = self._calculate_gst(obj)
        return half_gst




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
    