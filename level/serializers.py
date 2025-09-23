from rest_framework import serializers
from .models import Level, UserLevel, LevelPayment, get_referrer_details
import logging

logger = logging.getLogger(__name__)


class LevelCompletionSerializer(serializers.Serializer):
    total_referred_users = serializers.IntegerField()
    levels_completed_by_referred = serializers.IntegerField()
    percentage_completed = serializers.FloatField()

class LevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ['id', 'name', 'amount', 'order']

class UserLevelStatusSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.name')
    amount = serializers.DecimalField(source='level.amount', max_digits=10, decimal_places=2)

    class Meta:
        model = UserLevel
        fields = ['id', 'level_name', 'amount', 'is_active', 'status', 'pay_enabled', 'linked_user_id', 'balance', 'received']

class UserLevelFinancialSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.name')
    target = serializers.DecimalField(max_digits=12, decimal_places=2)
    received = serializers.DecimalField(max_digits=12, decimal_places=2)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    received_percent = serializers.SerializerMethodField()
    balance_percent = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['level_name', 'target', 'received', 'balance', 'received_percent', 'balance_percent']

    def get_received_percent(self, obj):
        if obj.target:
            return (obj.received / obj.target * 100) if obj.received else 0.0
        return 0.0

    def get_balance_percent(self, obj):
        if obj.target:
            return (obj.balance / obj.target * 100) if obj.balance else 0.0
        return 0.0

class UserLevelWithLinkSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.name')
    linked_user = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['level_name', 'status', 'linked_user','payment_status']

    def get_linked_user(self, obj):
        full_linked_user = get_referrer_details(obj.linked_user_id) or {}
        linked_user = {
            'user_id': full_linked_user.get('user_id', ''),
            'username': full_linked_user.get('username', '')
        }
        logger.debug(f"Serializing linked user for level {obj.level.name} (user {getattr(obj.user, 'user_id', 'unknown')}): {linked_user}")
        return linked_user
    def get_payment_status(self, obj):
        latest_payment = LevelPayment.objects.filter(user_level=obj).order_by('-created_at').first()
        return latest_payment.status if latest_payment else 'Pending'

class UserInfoSerializer(serializers.Serializer):
    username = serializers.SerializerMethodField()
    user_id = serializers.CharField(source='user.user_id', read_only=True, default='Unknown')
    levels_data = serializers.SerializerMethodField()
    refer_help_data = serializers.SerializerMethodField()
    user_status = serializers.SerializerMethodField()
    # payment_status = serializers.SerializerMethodField()

    def get_username(self, obj):
        user = obj.get('user')
        if not user:
            logger.error("No user provided to UserInfoSerializer")
            return 'Unknown'
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = full_name if full_name else getattr(user,'first_name','Unknown')
        # logger.debug(f"Resolved username for {getattr(user, 'user_id', 'unknown')}: {username}")
        return username



    def get_levels_data(self, obj):
        user = obj.get('user')
        if not user:
            logger.error("No user for levels data")
            return []
        try:
            user_levels = UserLevel.objects.filter(user=user, level__order__lte=6).order_by('level__order')
            logger.debug(f"Found {user_levels.count()} levels for user {getattr(user, 'user_id', 'unknown')}")
            return UserLevelWithLinkSerializer(user_levels, many=True).data
        except Exception as e:
            logger.error(f"Error fetching levels for {getattr(user, 'user_id', 'unknown')}: {str(e)}")
            return []

    def get_refer_help_data(self, obj):
        user = obj.get('user')
        if not user:
            logger.error("No user for refer_help data")
            return {'status': None, 'linked_user': {'user_id': '', 'username': ''}}
        try:
            refer_help = UserLevel.objects.filter(user=user, level__name='Refer Help').first()
            if refer_help:
                serializer = UserLevelWithLinkSerializer(refer_help)
                data = {'status': refer_help.status, 'linked_user': serializer.data['linked_user']}
                logger.debug(f"Refer Help for {getattr(user, 'user_id', 'unknown')}: {data}")
                return data
            logger.warning(f"No Refer Help level for {getattr(user, 'user_id', 'unknown')}")
            return {'status': None, 'linked_user': {'user_id': '', 'username': ''}}
        except Exception as e:
            logger.error(f"Error fetching Refer Help for {getattr(user, 'user_id', 'unknown')}: {str(e)}")
            return {'status': None, 'linked_user': {'user_id': '', 'username': ''}}

    def get_user_status(self, obj):
        user = obj.get('user')
        if not user:
            logger.error("No user for user_status")
            return False
        try:
            all_levels = UserLevel.objects.filter(user=user)
            unpaid_levels = all_levels.exclude(status='paid')
            status = unpaid_levels.count() == 0
            logger.debug(f"User {getattr(user, 'user_id', 'unknown')} status: {status}, unpaid levels: {unpaid_levels.count()}")
            return status
        except Exception as e:
            logger.error(f"Error checking user status for {getattr(user, 'user_id', 'unknown')}: {str(e)}")
            return False

class AdminPaymentReportSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    level_name = serializers.CharField(source='level.name')
    user_id = serializers.CharField(source='user.user_id')
    amount = serializers.DecimalField(source='level.amount', max_digits=10, decimal_places=2)
    payment_method = serializers.SerializerMethodField()
    transaction_id = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(allow_null=True)
    payment_proof_url = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    payment_id = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = [ 'username', 'level_name', 'user_id', 'amount', 'payment_method', 'transaction_id', 
                  'status', 'approved_at', 'payment_proof_url', 'created_at', 'requested_date','payment_id']
    
    def get_username(self, obj):
        return f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip() or obj.user.user_id

    def get_payment_method(self, obj):
        """Get the payment method from the latest LevelPayment."""
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        return getattr(latest_payment, 'payment_method', 'N/A') if latest_payment else 'N/A'

    def get_transaction_id(self, obj):
        """Get the transaction ID from the latest LevelPayment."""
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        return getattr(latest_payment, 'razorpay_payment_id', '') if latest_payment else ''

    def get_status(self, obj):
        """Get status based on UserLevel.status, refined by the latest LevelPayment.status."""
        # Start with UserLevel.status to match view filtering
        if obj.status == 'paid':
            return "Approved"
        elif obj.status == 'pending':
            latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
            if latest_payment and latest_payment.status == 'Verified':
                return "Approved"  # Override to Approved if payment is Verified
            return "Pending"
        return "Pending"  # Default for other statuses (e.g., 'not_paid', 'rejected')

    def get_payment_id(self, obj):
        """Get the id from the latest LevelPayment for pending payments."""
        if obj.status == 'pending':
            latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
            return getattr(latest_payment, 'id', None) if latest_payment else None
        return None

    def get_payment_proof_url(self, obj):
        """Get the payment proof URL from the latest LevelPayment."""
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        if latest_payment and latest_payment.payment_proof:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(latest_payment.payment_proof.url)
        return None

    def get_created_at(self, obj):
        """Get the created_at from the latest LevelPayment."""
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        return getattr(latest_payment, 'created_at', None) if latest_payment else None

    def to_representation(self, instance):
        """Ensure all fields are present with fallbacks."""
        representation = super().to_representation(instance)
        for field in self.fields:
            if representation.get(field) is None:
                representation[field] = 'N/A' if field not in ['amount', 'approved_at', 'created_at', 'requested_date'] else 0 if field == 'amount' else None
        return representation


# class LevelPaymentSerializer(serializers.ModelSerializer):
#     level_name = serializers.CharField(source='user_level.level.name')
#     user_id = serializers.CharField(source='user_level.user.user_id')

#     class Meta:
#         model = LevelPayment
#         fields = ['id', 'payment_token', 'level_name', 'user_id', 'amount', 'status', 
#                   'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature', 'created_at']



class LevelPaymentSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='user_level.level.name')
    user_id = serializers.CharField(source='user_level.user.user_id')
    username = serializers.SerializerMethodField()
    user_email = serializers.CharField(source='user_level.user.email', allow_null=True)
    payment_proof_url = serializers.SerializerMethodField()

    class Meta:
        model = LevelPayment
        fields = ['id', 'payment_token', 'level_name', 'user_id', 'username', 'user_email', 'amount', 'status', 
                  'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature', 'payment_proof_url', 'created_at']
    def get_username(self, obj):
        return f"{obj.user_level.user.first_name or ''} {obj.user_level.user.last_name or ''}".strip() or obj.user_level.user.user_id

    def get_payment_proof_url(self, obj):
        if obj.payment_proof:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.payment_proof.url)
        return None

class LevelRazorpayOrderSerializer(serializers.Serializer):
    user_level_id = serializers.IntegerField()

class LevelRazorpayVerifySerializer(serializers.Serializer):
    payment_token = serializers.UUIDField()
    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


class AdminPendingPaymentsSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='user_level.level.name')
    user_id = serializers.CharField(source='user_level.user.user_id')
    username = serializers.SerializerMethodField()
    user_email = serializers.CharField(source='user_level.user.email', allow_null=True)
    payment_method = serializers.CharField()
    payment_proof_url = serializers.SerializerMethodField()

    class Meta:
        model = LevelPayment
        fields = ['id', 'level_name', 'user_id', 'username', 'user_email', 'amount', 'status', 
                  'payment_method', 'payment_proof_url', 'created_at']

    def get_username(self, obj):
        return f"{obj.user_level.user.first_name or ''} {obj.user_level.user.last_name or ''}".strip() or obj.user_level.user.user_id

    def get_payment_proof_url(self, obj):
        if obj.payment_proof:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.payment_proof.url)
        return None

class ManualPaymentSerializer(serializers.Serializer):
    user_level_id = serializers.IntegerField()
    payment_proof = serializers.FileField()

class InitiatePaymentSerializer(serializers.Serializer):
    user_level_id = serializers.IntegerField()
    payment_method = serializers.ChoiceField(choices=['Razorpay', 'Manual'])
