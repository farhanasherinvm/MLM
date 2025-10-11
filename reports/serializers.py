from rest_framework import serializers
from level.models import UserLevel, LevelPayment
from users.models import CustomUser
from django.db.models import Count, Sum, Q,F
from datetime import datetime
from django.utils import timezone
from rest_framework import serializers
from django.urls import reverse
from decimal import Decimal


from django.core.exceptions import ObjectDoesNotExist

class LatestReferUserSerializer(serializers.Serializer):
    name = serializers.CharField()
    email_id = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    time = serializers.DateTimeField()

class LatestLevelPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    time = serializers.DateTimeField()
    done = serializers.BooleanField()

class LatestReportSerializer(serializers.Serializer):
    latest_refer_help = serializers.CharField()
    latest_refer_user = LatestReferUserSerializer()
    latest_level_help = serializers.CharField()
    latest_level_payment = LatestLevelPaymentSerializer()



class LevelPaymentReportSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='user_level.level.name')
    user_id = serializers.CharField(source='user_level.user.user_id')
    username = serializers.SerializerMethodField()

    class Meta:
        model = LevelPayment
        fields = ['id', 'payment_token', 'level_name', 'user_id', 'username', 'amount', 'status', 
                  'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature', 'created_at']

    def get_username(self, obj):
        return getattr(obj.user_level.user, 'email', getattr(obj.user_level.user, 'user_id', 'Unknown'))

class DashboardReportSerializer(serializers.Serializer):
    total_members = serializers.IntegerField()
    total_income = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_active_level_6 = serializers.IntegerField()
    new_users_per_level = serializers.ListField(child=serializers.DictField())
    recent_payments = serializers.ListField(child=LevelPaymentReportSerializer())
    new_user_registrations = serializers.ListField(child=serializers.DictField())
    latest_report = LatestReportSerializer()

    def to_representation(self, instance):
        return {
            'total_members': instance.get('total_members', 0),
            'total_income': instance.get('total_income', 0.00),
            'total_active_level_6': instance.get('total_active_level_6', 0),
            'new_users_per_level': instance.get('new_users_per_level', []),
            'recent_payments': instance.get('recent_payments', []),
            'new_user_registrations': instance.get('new_user_registrations', []),
            'latest_report': instance.get('latest_report', {
                'latest_refer_help': 'N/A',
                'latest_refer_user': {'name': 'N/A', 'email_id': 'N/A', 'first_name': 'N/A', 'last_name': 'N/A', 'amount': 0, 'time': 'N/A'},
                'latest_level_help': 'N/A',
                'latest_level_payment': {'amount': 0, 'time': 'N/A', 'done': False}
            })
        }


class SendRequestReportSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's name
    from_name = serializers.SerializerMethodField()  # Referred user's first_name + last_name
    username = serializers.SerializerMethodField()  #  user's user_id
    amount = serializers.SerializerMethodField()    # Amount from level
    linked_username = serializers.SerializerMethodField()  # Referred user's user_id
    status = serializers.SerializerMethodField()    # Converted status
    requested_date = serializers.SerializerMethodField()  # DateTime from UserLevel
    payment_method = serializers.SerializerMethodField()  # Payment method or proof link
    level = serializers.SerializerMethodField()    # Level name

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username', 'from_name', 'amount', 'status', 'requested_date', 'payment_method', 'level','linked_username']
        extra_kwargs = {
            'requested_date': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        """
        Validate the data to ensure consistency with frontend input.
        """
        request = self.context.get('request')
        if not request:
            raise serializers.ValidationError("Request context is missing.")
        return data

    def get_from_user(self, obj):
        """Get the current user's full name."""
        user = getattr(obj, 'user', None)
        if user:
            full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            return full_name if full_name else 'N/A'
        return 'N/A'

    def get_from_name(self, obj):
        """Get the linked user's full name."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                full_name = f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
                return full_name if full_name else 'Unknown'
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_username(self, obj):
        """Get the current user's user_id."""
        user = getattr(obj, 'user', None)
        if user:
            return getattr(user, 'user_id', 'N/A')
        return 'N/A'

    def get_amount(self, obj):
        """Get the amount from the associated level."""
        return getattr(obj.level, 'amount', 0) if obj.level else 0

    def get_status(self, obj):
        """Convert status to 'Completed' or 'Pending'."""
        return "Completed" if getattr(obj, 'status', '') == 'paid' else "Pending"

    def get_requested_date(self, obj):
        """Get the requested date with proper formatting."""
        requested_date = getattr(obj, 'requested_date', None)
        return requested_date.strftime("%Y-%m-%d %H:%M:%S") if requested_date else None

    def get_payment_method(self, obj):
        """Determine payment method with URL for proof if Manual."""
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        if latest_payment:
            if latest_payment.payment_method == 'Razorpay':
                return 'Razorpay'
            elif latest_payment.payment_method == 'Manual':
                if hasattr(latest_payment, 'payment_proof') and latest_payment.payment_proof:
                    request = self.context.get('request')
                    if request:
                        proof_url = request.build_absolute_uri(latest_payment.payment_proof.url)
                        return proof_url if proof_url.startswith('http') else 'Manual'
                return 'Manual'
        return 'N/A'

    def get_linked_username(self, obj):
        """Get the referred user's user_id (assuming linked_user_id is the referred user)."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_level(self, obj):
        """Get the level name from the associated level."""
        return getattr(obj.level, 'name', 'N/A') if obj.level else 'N/A'

    def to_representation(self, instance):
        """Ensure all fields are present with fallbacks."""
        representation = super().to_representation(instance)
        for field in self.fields:
            if representation.get(field) is None:
                representation[field] = 'N/A' if field not in ['amount', 'requested_date'] else 0 if field == 'amount' else None
        return representation


class AUCReportSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's user_id
    username = serializers.SerializerMethodField()  #  user's user_id
    from_name = serializers.SerializerMethodField()  # Referred user's first_name + last_name
    linked_username = serializers.SerializerMethodField()  # Referred user's user_id
    amount = serializers.SerializerMethodField()    # Amount from level
    status = serializers.SerializerMethodField()    # Converted status
    date = serializers.SerializerMethodField()      # Requested date
    payment_method = serializers.SerializerMethodField()  # Payment method or proof link

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username', 'from_name', 'linked_username', 'amount', 'status', 'date', 'payment_method']
        extra_kwargs = {
            'date': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        """Validate the data to ensure consistency with frontend input."""
        request = self.context.get('request')
        if not request:
            raise serializers.ValidationError("Request context is missing.")
        return data

    def get_from_user(self, obj):
        """Get the current user's full name."""
        user = getattr(obj, 'user', None)
        if user:
            full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            return full_name if full_name else 'N/A'
        return 'N/A'

    def get_username(self, obj):
        """Get the current user's user_id."""
        user = getattr(obj, 'user', None)
        if user:
            return getattr(user, 'user_id', 'N/A')
        return 'N/A'

    

    def get_from_name(self, obj):
        """Get the linked user's full name."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                full_name = f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
                return full_name if full_name else 'Unknown'
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_linked_username(self, obj):
        """Get the referred user's user_id (assuming linked_user_id is the referred user)."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_amount(self, obj):
        """Get the amount from the associated level."""
        return getattr(obj.level, 'amount', 0) if obj.level else 0

    def get_status(self, obj):
        """Convert status to 'Completed' or 'Pending'."""
        return "Completed" if getattr(obj, 'status', '') == 'paid' else "Pending"

    def get_date(self, obj):
        """Get the requested date with proper formatting."""
        requested_date = getattr(obj, 'requested_date', None)
        return requested_date.strftime("%Y-%m-%d %H:%M:%S") if requested_date else None

    def get_payment_method(self, obj):
        """Determine payment method with URL for proof if Manual."""
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        if latest_payment:
            if latest_payment.payment_method == 'Razorpay':
                return 'Razorpay'
            elif latest_payment.payment_method == 'Manual':
                if hasattr(latest_payment, 'payment_proof') and latest_payment.payment_proof:
                    request = self.context.get('request')
                    if request:
                        proof_url = request.build_absolute_uri(latest_payment.payment_proof.url)
                        return proof_url if proof_url.startswith('http') else 'Manual'
                return 'Manual'
        return 'N/A'

    def to_representation(self, instance):
        """Ensure all fields are present with fallbacks."""
        representation = super().to_representation(instance)
        for field in self.fields:
            if representation.get(field) is None:
                representation[field] = 'N/A' if field not in ['amount', 'date'] else 0 if field == 'amount' else None
        return representation


class PaymentReportSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's user_id
    username = serializers.SerializerMethodField()  # Referred user's user_id
    from_name = serializers.SerializerMethodField()  # Referred user's first_name + last_name
    linked_username = serializers.SerializerMethodField()  # Referred user's user_id
    amount = serializers.SerializerMethodField()    # Amount from level
    payout_amount = serializers.SerializerMethodField()  # Payout amount
    transaction_fee = serializers.SerializerMethodField()  # Transaction fee
    status = serializers.SerializerMethodField()    # Converted status
    requested_date = serializers.SerializerMethodField()  # Requested date
    total = serializers.SerializerMethodField()     # Total amount

    class Meta:
        model = UserLevel
        fields = ['id','from_user', 'username', 'from_name', 'linked_username', 'amount', 'payout_amount', 'transaction_fee', 'status', 'requested_date', 'total']
        extra_kwargs = {
            'requested_date': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        """Validate the data to ensure consistency with frontend input."""
        request = self.context.get('request')
        if not request:
            raise serializers.ValidationError("Request context is missing.")
        return data

    def get_from_user(self, obj):
        """Get the current user's full name."""
        user = getattr(obj, 'user', None)
        if user:
            full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            return full_name if full_name else 'N/A'
        return 'N/A'

    

    def get_username(self, obj):
        """Get the current user's user_id."""
        user = getattr(obj, 'user', None)
        if user:
            return getattr(user, 'user_id', 'N/A')
        return 'N/A'

    

    def get_from_name(self, obj):
        """Get the linked user's full name."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                full_name = f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
                return full_name if full_name else 'Unknown'
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_linked_username(self, obj):
        """Get the referred user's user_id (assuming linked_user_id is the referred user)."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_amount(self, obj):
        """Get the amount from the associated level."""
        return getattr(obj.level, 'amount', 0) if obj.level else 0

    def get_payout_amount(self, obj):
        """Get the payout amount (assuming it's derived from received or a custom field)."""
        return getattr(obj, 'received', 0) if hasattr(obj, 'received') else 0

    def get_transaction_fee(self, obj):
        """Get the transaction fee (assuming it's a custom field or calculated)."""
        return getattr(obj, 'transaction_fee', 0) if hasattr(obj, 'transaction_fee') else 0

    def get_status(self, obj):
        """Convert status to 'Completed' or 'Pending'."""
        return "Completed" if getattr(obj, 'status', '') == 'paid' else "Pending"

    def get_requested_date(self, obj):
        """Get the requested date with proper formatting."""
        requested_date = getattr(obj, 'requested_date', None)
        return requested_date.strftime("%Y-%m-%d %H:%M:%S") if requested_date else None

    def get_total(self, obj):
        """Get the total amount (same as amount for now)."""
        return getattr(obj.level, 'amount', 0) if obj.level else 0

    def to_representation(self, instance):
        """Ensure all fields are present with fallbacks."""
        representation = super().to_representation(instance)
        for field in self.fields:
            if representation.get(field) is None:
                representation[field] = 'N/A' if field not in ['amount', 'payout_amount', 'transaction_fee', 'requested_date'] else 0 if field in ['amount', 'payout_amount', 'transaction_fee'] else None
        return representation



class BonusSummaryDataSerializer(serializers.Serializer):
    """Calculates a single, aggregated income statement summary for a user."""
    user_id = serializers.CharField(read_only=True)
    username = serializers.CharField(read_only=True)
    statement_date = serializers.CharField(read_only=True)
    referral_bonus = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    level_help = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    rank_bonus = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    send_help = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    received_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    def to_representation(self, user):
        # Data Aggregation Logic:
        sent_help_sum = UserLevel.objects.filter(
            user=user, 
            status='paid',
        ).exclude(level__name='Refer Help').aggregate(Sum('level__amount'))['level__amount__sum'] or Decimal('0.00')

        received_total = UserLevel.objects.filter(
            user=user
        ).aggregate(Sum('received'))['received__sum'] or Decimal('0.00')
        
        # Placeholders for breakdown (modify with your actual logic if available)
        referral_bonus = Decimal('0.00')
        level_help = Decimal('0.00')
        rank_bonus = Decimal('0.00')
        
        return {
            'user_id': user.user_id,
            'username': f"{user.first_name} {user.last_name}".strip(),
            'statement_date': timezone.now().strftime('%Y-%m-%d'),
            'referral_bonus': referral_bonus,
            'level_help': level_help,
            'rank_bonus': rank_bonus,
            'send_help': sent_help_sum,
            'net_amount': sent_help_sum,
            'received_total': received_total,
        }

class UserBonusListSerializer(serializers.ModelSerializer):
    """Serializer for listing users and generating PDF download links."""
    full_name = serializers.SerializerMethodField()
    pdf_download_url = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id','user_id', 'full_name', 'email', 'pdf_download_url']
        
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_pdf_download_url(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        
        try:
            
            pdf_path = reverse('single-user-bonus-detail', kwargs={'user_id': obj.user_id})
            return request.build_absolute_uri(f"{pdf_path}?export=pdf")
            
        except Exception:
            # Fallback for debugging 
            return f"Error: Check URL config for user {obj.user_id}"


class LevelUsersSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's user_id
    from_name = serializers.SerializerMethodField()  # Referred user's first_name + last_name
    username = serializers.SerializerMethodField()  # Referred user's user_id
    linked_username = serializers.SerializerMethodField()  # Referred user's user_id
    amount = serializers.SerializerMethodField()    # Amount from level
    status = serializers.SerializerMethodField()    # Converted status
    level = serializers.SerializerMethodField()    # Level name
    requested_date = serializers.SerializerMethodField()  # Requested date
    total = serializers.SerializerMethodField()     # Total amount
    payment_method = serializers.SerializerMethodField()  # Payment method or proof link

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username', 'from_name', 'linked_username', 'amount', 'status', 'level', 'requested_date', 'total', 'payment_method']
        extra_kwargs = {
            'requested_date': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        """Validate the data to ensure consistency with frontend input."""
        request = self.context.get('request')
        if not request:
            raise serializers.ValidationError("Request context is missing.")
        return data

    def get_from_user(self, obj):
        """Get the current user's full name."""
        user = getattr(obj, 'user', None)
        if user:
            full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            return full_name if full_name else 'N/A'
        return 'N/A'

    def get_from_name(self, obj):
        """Get the linked user's full name."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                full_name = f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
                return full_name if full_name else 'Unknown'
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_username(self, obj):
        """Get the current user's user_id."""
        user = getattr(obj, 'user', None)
        if user:
            return getattr(user, 'user_id', 'N/A')
        return 'N/A'

    def get_linked_username(self, obj):
        """Get the referred user's user_id (assuming linked_user_id is the referred user)."""
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except ObjectDoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_amount(self, obj):
        """Get the amount from the associated level."""
        return getattr(obj.level, 'amount', 0) if obj.level else 0

    def get_status(self, obj):
        """Convert status to 'Completed' or 'Pending'."""
        return "Completed" if getattr(obj, 'status', '') == 'paid' else "Pending"

    def get_level(self, obj):
        """Get the level name from the associated level."""
        return getattr(obj.level, 'name', 'N/A') if obj.level else 'N/A'

    def get_requested_date(self, obj):
        """Get the requested date with proper formatting."""
        requested_date = getattr(obj, 'requested_date', None)
        return requested_date.strftime("%Y-%m-%d %H:%M:%S") if requested_date else None

    def get_total(self, obj):
        """Get the total amount (same as amount for now)."""
        return getattr(obj.level, 'amount', 0) if obj.level else 0

    def get_payment_method(self, obj):
        """Determine payment method with URL for proof if Manual."""
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        if latest_payment:
            if latest_payment.payment_method == 'Razorpay':
                return 'Razorpay'
            elif latest_payment.payment_method == 'Manual':
                if hasattr(latest_payment, 'payment_proof') and latest_payment.payment_proof:
                    request = self.context.get('request')
                    if request:
                        proof_url = request.build_absolute_uri(latest_payment.payment_proof.url)
                        return proof_url if proof_url.startswith('http') else 'Manual'
                return 'Manual'
        return 'N/A'

    def to_representation(self, instance):
        """Ensure all fields are present with fallbacks."""
        representation = super().to_representation(instance)
        for field in self.fields:
            if representation.get(field) is None:
                representation[field] = 'N/A' if field not in ['amount', 'requested_date', 'total'] else 0 if field in ['amount', 'total'] else None
        return representation