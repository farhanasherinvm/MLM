from rest_framework import serializers
from level.models import UserLevel, LevelPayment
from users.models import CustomUser
from django.db.models import Count, Sum, Q,F
from datetime import datetime
from django.utils import timezone

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
    from_user = serializers.SerializerMethodField()  # Current user's first_name + last_name
    from_name = serializers.SerializerMethodField()  # Linked user's first_name + last_name
    username = serializers.SerializerMethodField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    status = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", allow_null=True)
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username','from_name', 'amount', 'status', 'approved_at','payment_method']

    def get_from_user(self, obj):
        user = getattr(obj, 'user', None)
        return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() if user else 'Unknown'

    def get_from_name(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'
    def get_username(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_status(self, obj):
        return "Completed" if obj.status == 'paid' else "Pending"
    
    def get_payment_method(self, obj):
        latest_payment = obj.payments.order_by('-created_at').first()
        if latest_payment:
            if latest_payment.payment_method == 'Razorpay':
                return 'Razorpay'
            elif latest_payment.payment_method == 'Manual':
                if latest_payment.payment_proof:
                    # Construct the URL for the uploaded file (assuming media is served)
                    request = self.context.get('request')
                    if request:
                        return request.build_absolute_uri(latest_payment.payment_proof.url)
                return 'Manual'
        return 'N/A'

class AUCReportSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's first_name + last_name
    from_name = serializers.SerializerMethodField()  # Linked user's first_name + last_name
    username = serializers.SerializerMethodField()  # Current user's user_id
    linked_username = serializers.SerializerMethodField()  # Linked user's user_id
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    status = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source='approved_at', format="%Y-%m-%d %H:%M:%S", allow_null=True)
    payment_method = serializers.SerializerMethodField()  # Payment method or proof link

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username', 'from_name', 'linked_username', 'amount', 'status', 'date', 'payment_method']

    def get_from_user(self, obj):
        user = getattr(obj, 'user', None)
        return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() if user else 'Unknown'

    def get_from_name(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_username(self, obj):
        user = getattr(obj, 'user', None)
        return getattr(user, 'user_id', 'N/A') if user else 'N/A'

    def get_linked_username(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_status(self, obj):
        return "Completed" if obj.status == 'paid' else "Pending"

    def get_payment_method(self, obj):
        latest_payment = obj.payments.order_by('-created_at').first()
        if latest_payment:
            if latest_payment.payment_method == 'Razorpay':
                return 'Razorpay'
            elif latest_payment.payment_method == 'Manual':
                if latest_payment.payment_proof:
                    request = self.context.get('request')
                    if request:
                        return request.build_absolute_uri(latest_payment.payment_proof.url)
                return 'Manual'
        return 'N/A'

class PaymentReportSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's first_name + last_name
    from_name = serializers.SerializerMethodField()  # Linked user's first_name + last_name
    username = serializers.SerializerMethodField()  # Current user's user_id
    linked_username = serializers.SerializerMethodField()  # Linked user's user_id
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    payout_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    transaction_fee = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", allow_null=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username', 'from_name', 'linked_username', 'amount', 'payout_amount', 'transaction_fee', 'status', 'approved_at', 'total']

    def get_from_user(self, obj):
        user = getattr(obj, 'user', None)
        return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() if user else 'Unknown'

    def get_from_name(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_username(self, obj):
        user = getattr(obj, 'user', None)
        return getattr(user, 'user_id', 'N/A') if user else 'N/A'

    def get_linked_username(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_status(self, obj):
        return "Completed" if obj.status == 'paid' else "Pending"


class BonusSummarySerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's first_name + last_name
    from_name = serializers.SerializerMethodField()  # Linked user's first_name + last_name
    username = serializers.CharField(source='user.user_id')  # Current user's user_id
    linked_username = serializers.SerializerMethodField()  # Linked user's user_id
    bonus_amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='received')  # Bonus received
    status = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", allow_null=True)
    total_bonus = serializers.DecimalField(max_digits=12, decimal_places=2, source='received')  # Total bonus

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username', 'from_name', 'linked_username', 'bonus_amount', 'status', 'approved_at', 'total_bonus']

    def get_from_user(self, obj):
        user = getattr(obj, 'user', None)
        return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() if user else 'Unknown'

    def get_from_name(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_linked_username(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_status(self, obj):
        return "Completed" if obj.status == 'paid' else "Pending"

class LevelUsersSerializer(serializers.ModelSerializer):
    from_user = serializers.SerializerMethodField()  # Current user's first_name + last_name
    from_name = serializers.SerializerMethodField()  # Linked user's first_name + last_name
    username = serializers.CharField(source='user.user_id')  # Current user's user_id
    linked_username = serializers.SerializerMethodField()  # Linked user's user_id
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    status = serializers.SerializerMethodField()
    level = serializers.CharField(source='level.name')
    approved_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", allow_null=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['from_user', 'username', 'from_name', 'linked_username', 'amount', 'status', 'level', 'approved_at', 'total', 'payment_method']

    def get_from_user(self, obj):
        user = getattr(obj, 'user', None)
        return f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() if user else 'Unknown'

    def get_from_name(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_linked_username(self, obj):
        linked_user_id = getattr(obj, 'linked_user_id', None)
        if linked_user_id:
            try:
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                return getattr(linked_user, 'user_id', 'Unknown')
            except CustomUser.DoesNotExist:
                return 'Unknown'
        return 'N/A'

    def get_status(self, obj):
        return "Completed" if obj.status == 'paid' else "Pending"

    def get_payment_method(self, obj):
        latest_payment = obj.payments.order_by('-created_at').first()
        if latest_payment:
            if latest_payment.payment_method == 'Razorpay':
                return 'Razorpay'
            elif latest_payment.payment_method == 'Manual':
                if latest_payment.payment_proof:
                    # Construct the URL for the uploaded file (assuming media is served)
                    request = self.context.get('request')
                    if request:
                        return request.build_absolute_uri(latest_payment.payment_proof.url)
                return 'Manual'
        return 'N/A'


