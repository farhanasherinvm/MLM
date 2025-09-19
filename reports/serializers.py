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
    date = serializers.DateTimeField(allow_null=True)

    class Meta:
        model = UserLevel
        fields = ['username', 'level_name', 'amount', 'payment_mode', 'transaction_id', 'status', 'date']
    
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
    username = serializers.CharField(source='user.user_id')
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    status = serializers.CharField()
    level = serializers.CharField(source='level.name')
    date = serializers.DateTimeField(source='approved_at', format="%Y-%m-%d %H:%M:%S", allow_null=True)

    class Meta:
        model = UserLevel
        fields = ['from_name', 'username', 'amount', 'status', 'level', 'date']

    def get_from_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()

class AUCReportSerializer(serializers.ModelSerializer):
    from_user = serializers.CharField(source='user.user_id')
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    status = serializers.CharField()
    date = serializers.DateTimeField(source='approved_at', format="%Y-%m-%d %H:%M:%S", allow_null=True)

    class Meta:
        model = UserLevel
        fields = ['from_user', 'amount', 'status', 'date']

class PaymentReportSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.user_id')
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    payout_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)  # Placeholder
    transaction_fee = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)  # Placeholder
    status = serializers.CharField()
    date = serializers.DateTimeField(source='approved_at', format="%Y-%m-%d %H:%M:%S", allow_null=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['username', 'amount', 'payout_amount', 'transaction_fee', 'status', 'date', 'total']

    def get_total(self, obj):
        return obj.level.amount  # Fallback to amount since payout_amount and transaction_fee are placeholders

# class BonusSummarySerializer(serializers.Serializer):
#     username = serializers.CharField()
#     from_name = serializers.CharField()
#     total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
#     completed_levels = serializers.IntegerField()
#     latest_status = serializers.CharField()
#     latest_date = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", allow_null=True)

#     def to_representation(self, instance):
#         user = instance['user']
#         user_levels = instance['user_levels']
#         total_amount = user_levels.filter(status='paid').aggregate(total=Sum('level.amount'))['total'] or 0
#         completed_levels = user_levels.filter(status='paid').count()
#         latest_level = user_levels.order_by('-approved_at').first()
#         return {
#             'username': user.user_id,
#             'from_name': f"{user.first_name} {user.last_name}".strip(),
#             'total_amount': total_amount,
#             'completed_levels': completed_levels,
#             'latest_status': latest_level.status if latest_level else 'N/A',
#             'latest_date': latest_level.approved_at.strftime('%Y-%m-%d %H:%M:%S') if latest_level and latest_level.approved_at else None
#         }

class LevelUsersSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.user_id')
    from_name = serializers.SerializerMethodField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, source='level.amount')
    status = serializers.CharField()
    level = serializers.CharField(source='level.name')
    date = serializers.DateTimeField(source='approved_at', format="%Y-%m-%d %H:%M:%S", allow_null=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ['username', 'from_name', 'amount', 'status', 'level', 'date', 'total']

    def get_from_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()

    def get_total(self, obj):
        return obj.level.amount  # Fallback to amount


