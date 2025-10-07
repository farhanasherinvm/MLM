from rest_framework import serializers
from .models import Level, UserLevel, LevelPayment, get_referrer_details
import logging
import json
from decimal import Decimal
from users.models import CustomUser
from django.utils import timezone
from profiles.models import Profile
from django.conf import settings
import random
import uuid
from django.db import transaction
import string
from django.db.models import Q
from django.contrib.auth.hashers import make_password


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
        fields = [ 'id','username', 'level_name', 'user_id', 'amount', 'payment_method', 'transaction_id', 
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
        latest_payment = getattr(obj, 'payments', []).order_by('-created_at').first()
        # Return the primary key (id) of the LevelPayment object
        return getattr(latest_payment, 'id', None) if latest_payment else None

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
    payment_proof = serializers.FileField(required=False)

class InitiatePaymentSerializer(serializers.Serializer):
    user_level_id = serializers.IntegerField()
    payment_method = serializers.ChoiceField(choices=['Razorpay', 'Manual'])



class UpdateLinkedUserIdSerializer(serializers.ModelSerializer):
    linked_user_id = serializers.CharField(max_length=20, allow_blank=True, required=False)

    class Meta:
        model = UserLevel
        fields = ['id', 'linked_user_id']

    def validate_linked_user_id(self, value):
        # Allow blank/empty string to clear the linked user ID
        if not value:
            return value
            
        # Only validate existence if a non-empty value is provided
        if not CustomUser.objects.filter(user_id=value).exists():
            raise serializers.ValidationError("Invalid user_id. User does not exist.")
            
        return value

class LinkedUserLevelSerializer(serializers.ModelSerializer):
    payer_user_id = serializers.CharField(source='user.user_id')
    payer_name = serializers.CharField(source='user.get_full_name', read_only=True)
    level_name = serializers.CharField(source='level.name')

    class Meta:
        model = UserLevel
        fields = ('id', 'payer_user_id', 'payer_name', 'level_name', 'requested_date')


class RecipientLevelPaymentSerializer(serializers.ModelSerializer):
    user_level = LinkedUserLevelSerializer(read_only=True)
    payment_proof_url = serializers.FileField(source='payment_proof', read_only=True)
    
    payment_token = serializers.UUIDField(read_only=True) 

    class Meta:
        model = LevelPayment
        fields = ('id', 'payment_token', 'user_level', 'amount', 'payment_method', 
                  'razorpay_order_id', 'payment_proof_url', 'created_at', 'payment_data')
        read_only_fields = ('id', 'payment_token', 'user_level', 'amount', 'payment_method', 
                            'razorpay_order_id', 'payment_proof_url', 'created_at', 'payment_data')

                            

class DummyUserSerializer(serializers.Serializer):
    user_id = serializers.CharField(max_length=20, source='user.user_id')
    first_name = serializers.CharField(max_length=100, source='user.first_name')
    email = serializers.EmailField(source='user.email')
    pk = serializers.IntegerField(read_only=True)
    admin_level_linked = serializers.SerializerMethodField()
    current_status_display = serializers.SerializerMethodField()
    linked_user_id = serializers.CharField(max_length=20)
    is_active = serializers.BooleanField()
    node_type = serializers.SerializerMethodField() 
    total_income = serializers.SerializerMethodField()
    mobile = serializers.CharField(source='user.mobile', read_only=True)
    whatsapp_number = serializers.CharField(source='user.whatsapp_number', read_only=True)
    pincode = serializers.CharField(source='user.pincode', read_only=True)
    upi_number = serializers.CharField(source='user.upi_number', read_only=True)

    sponsor_id = serializers.CharField(source='user.sponsor_id', read_only=True) 
    placement_id = serializers.CharField(source='user.placement_id', read_only=True) 
    

    def get_admin_level_linked(self, obj):
        return obj.level.name if obj.level else "N/A"

    def get_current_status_display(self, obj):
        if not obj.is_active:
            return "INACTIVE (Admin Disabled)"
        if obj.status == 'not_paid':
            return "ACTIVE (Payment Pending)"
        return f"ACTIVE ({obj.status.replace('_', ' ').title()})"
        
    def get_total_income(self, obj):
        return obj.received
        
    def get_node_type(self, obj):
        user_id = obj.user.user_id
        if user_id.startswith('MASTER'):
            return "MASTER Node"
        elif user_id.startswith('DUMMY'):
            return "OLD Dummy Data "
        return "Unknown Node Type"

class CreateDummyUsersSerializer(serializers.Serializer):
    # Form Fields (Input fields REMAIN THE SAME)
    sponsor_name = serializers.CharField(max_length=150)
    placement_id = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=True)
    mobile = serializers.CharField(max_length=15)
    whatsapp_number = serializers.CharField(max_length=15, allow_blank=True)
    pincode = serializers.CharField(max_length=10)
    select_payment_type = serializers.CharField(max_length=50) 
    upi_number = serializers.CharField(max_length=50, allow_blank=True)
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def get_unique_suffix(self, length=4):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return data

    @transaction.atomic
    def create(self, validated_data):
        admin = self.context['request'].user
        
        # 1. ID Generation Logic (MASTER Prefix)
        all_dummy_users = CustomUser.objects.filter(
            Q(user_id__startswith='DUMMY') | Q(user_id__startswith='FAKEDATA') | Q(user_id__startswith='MASTER')
        ).values_list('user_id', flat=True)
        
        highest_numeric_id = 0
        for user_id in all_dummy_users:
            try:
                numeric_part = ''.join(filter(str.isdigit, user_id.replace('DUMMY', '').replace('FAKEDATA', '').replace('MASTER', '')))
                if numeric_part: highest_numeric_id = max(highest_numeric_id, int(numeric_part))
            except ValueError: pass
        
        new_id_num = highest_numeric_id + 1
        new_user_id = f'MASTER{new_id_num:04d}'

        # 2. DETERMINE is_active STATUS BASED ON SLOT AVAILABILITY (AUTOMATIC)
        admin_levels_queryset = UserLevel.objects.filter(user=admin).exclude(level__name='Refer Help').order_by('level__order')
        occupied_slots_count = admin_levels_queryset.exclude(linked_user_id__isnull=True).exclude(linked_user_id__exact='').count()
        
        can_be_active = (occupied_slots_count < 6)
        assigned_level = None
        
        if can_be_active:
            available_slot_ul = admin_levels_queryset.filter(linked_user_id__isnull=True).order_by('level__order').first()
            if available_slot_ul:
                 assigned_level = available_slot_ul.level
            else:
                 can_be_active = False # No specific level slot found

        # 3. Create CustomUser using the auto-calculated 'can_be_active'
        user = CustomUser.objects.create(
            user_id=new_user_id,
            first_name=validated_data['first_name'], last_name=validated_data['last_name'],
            email=validated_data['email'], mobile=validated_data['mobile'],
            sponsor_id=validated_data['sponsor_name'], placement_id=validated_data['placement_id'],
            pincode=validated_data['pincode'], 
            is_active=can_be_active,
            whatsapp_number=validated_data['whatsapp_number'],
            upi_number=validated_data['upi_number'],
            password=make_password(validated_data['password']), date_of_joining=timezone.now()
        )

        # 4. Create UserLevel record
        # Status is set to 'paid' immediately as no payment is required from this user.
        user_level = UserLevel.objects.create(
            user=user, 
            level=assigned_level, 
            linked_user_id=admin.user_id,
            is_active=can_be_active,
            payment_mode=validated_data['select_payment_type'], 
            status='paid' # <-- SET TO 'paid' (or equivalent)
        )

   
        # 6. Link Admin's slot
        if assigned_level:
            UserLevel.objects.filter(user=admin, level=assigned_level).update(linked_user_id=user.user_id)

        return user_level


# --- 3. AdminDummyUserUpdateSerializer (Multi-Model Update/PATCH) ---
class AdminDummyUserUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    mobile = serializers.CharField(max_length=15, required=False)
    is_active = serializers.BooleanField(required=False)
    level = serializers.PrimaryKeyRelatedField(queryset=Level.objects.all(), required=False)
    status = serializers.ChoiceField(
        choices=[('not_paid', 'Not Paid'), ('paid', 'Paid'), ('pending', 'Pending'), ('rejected', 'Rejected')],
        required=False
    )
    user_id = serializers.CharField(source='user.user_id', read_only=True)
    linked_user_id = serializers.CharField(read_only=True)
    pk = serializers.IntegerField(read_only=True)

    def validate(self, data):
        instance = self.instance
        admin = self.context['request'].user

        if 'level' in data and data['level'] != instance.level and not instance.is_active:
            raise serializers.ValidationError({"level": "Cannot change the level of an inactive dummy user. Activate the user first."})

        if 'is_active' in data and data['is_active'] is True and instance.is_active is False:
            current_user_pk = instance.user.pk

            # Step 1: Get the 'user_id's of all active Master/Dummy users in the system, EXCLUDING the current user.
            active_master_ids = CustomUser.objects.filter(
                Q(user_id__startswith='MASTER') | Q(user_id__startswith='DUMMY'),
                is_active=True
            ).exclude(
                pk=current_user_pk
            ).values_list('user_id', flat=True)
            
            # Step 2: Count how many of the Admin's slots are occupied by one of these active IDs.
            occupied_slots_count = UserLevel.objects.filter(
                user=admin,                        # Filter 1: Slots belonging to the admin
                linked_user_id__in=active_master_ids, # Filter 2: Slot is occupied by an active master/dummy user
                linked_user_id__isnull=False,      # Ensure it's linked
            ).count()

            if occupied_slots_count >= 6:
                error_message = f"Activation failed. The maximum limit of 6 active dummy users has been reached. Current active count: {occupied_slots_count}."
                raise serializers.ValidationError({"is_active": error_message})

        if 'email' in data and data['email'] != instance.user.email:
            if CustomUser.objects.filter(email=data['email']).exclude(pk=instance.user.pk).exists():
                raise serializers.ValidationError({"email": "This email is already in use by another user."})
        return data
    @transaction.atomic
    def update(self, instance, validated_data):
        original_level = instance.level 
        new_level = validated_data.get('level')
        
        user_data_to_update = {}
        for field in ['first_name', 'last_name', 'email', 'mobile']:
            if field in validated_data:
                user_data_to_update[field] = validated_data[field]
        if user_data_to_update:
            CustomUser.objects.filter(pk=instance.user.pk).update(**user_data_to_update)
            instance.user.refresh_from_db()

        for field in ['is_active', 'level', 'status']:
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.save() 
        updated_instance = instance
        
        is_level_changed = new_level and original_level and original_level.pk != new_level.pk
        
        if is_level_changed and updated_instance.is_active:
            admin = self.context['request'].user
            moving_dummy_user_id = updated_instance.user.user_id
            new_level_id = new_level.pk
            
            admin_new_level_slot = UserLevel.objects.filter(user=admin, level_id=new_level_id).first()
            overwritten_user_id = admin_new_level_slot.linked_user_id if admin_new_level_slot else None
            if overwritten_user_id:
                UserLevel.objects.filter(user__user_id=overwritten_user_id, linked_user_id__isnull=True).update(level=None, is_active=False)

            UserLevel.objects.filter(user=admin, level=original_level, linked_user_id=moving_dummy_user_id).update(linked_user_id=None)
            UserLevel.objects.filter(user=admin, level_id=new_level_id).update(linked_user_id=moving_dummy_user_id)
            
        return updated_instance