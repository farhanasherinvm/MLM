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

class PaymentReportSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    level_name = serializers.CharField(source='level.name')
    amount = serializers.DecimalField(source='level.amount', max_digits=10, decimal_places=2)
    payment_mode = serializers.CharField()
    transaction_id = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    approved_at = serializers.DateTimeField(allow_null=True)

    class Meta:
        model = UserLevel
        fields = ['username', 'level_name', 'amount', 'payment_mode', 'transaction_id', 'status', 'approved_at']
    
    def get_username(self, obj):
        return getattr(obj.user, 'email', getattr(obj.user, 'user_id', 'Unknown'))

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
    from_name = serializers.SerializerMethodField()
    user_id = serializers.CharField(source='user.user_id')
    amount = serializers.DecimalField(source='level.amount',max_digits=10,decimal_places=2,read_only=True)
    # proof = serializers.URLField(source='proof_url', allow_null=True)  # Assume proof_url field added to UserLevel
    status = serializers.CharField()
    level = serializers.CharField(source='level.name')
    requested__date = serializers.DateTimeField(source='requested_date')

    class Meta:
        model = UserLevel
        fields = ['from_name', 'user_id', 'amount', 'proof', 'status', 'level', 'requested__date']

    def get_from_name(self, obj):
        # Assume from_name is sponsor's name or user's own name
        return f"{obj.user.first_name} {obj.user.last_name}".strip()

class AUCRequestSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source='user.user_id')
    amount = serializers.DecimalField(source='level.amount',max_digits=10,decimal_places=2,read_only=True)
    status = serializers.CharField()
    date = serializers.DateTimeField(source='approved_at')

    class Meta:
        model = UserLevel
        fields = ['user', 'amount', 'status', 'date']

class LevelUsersSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.user_id')
    from_name = serializers.SerializerMethodField()
    amount = serializers.DecimalField(source='level.amount',max_digits=10,decimal_places=2,read_only=True)
    proof = serializers.URLField(source='proof_url', allow_null=True)
    status = serializers.CharField()
    level = serializers.CharField(source='level.name')
    requested__date = serializers.DateTimeField(source='requested_date')
    total = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['username', 'from_name', 'amount', 'proof', 'status', 'level', 'requested__date', 'total']

    def get_from_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()

    def get_total(self, obj):
        base_amount = obj.level.amount or 0
        transaction_fee = getattr(obj, 'transaction_fee', 0)
        payout_amount = getattr(obj, 'payout_amount', 0)
        return base_amount - transaction_fee + payout_amount