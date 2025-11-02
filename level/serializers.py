from rest_framework import serializers
from .models import Level, UserLevel, LevelPayment, get_referrer_details,check_upline_fully_paid, PmfPayment
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
from django.db.models import Q, Sum
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
    amount = serializers.SerializerMethodField()
    is_upline_fully_paid = serializers.SerializerMethodField() # <-- ADD THIS
    can_pay_now = serializers.SerializerMethodField() 
    level_name = serializers.SerializerMethodField()
    target = serializers.DecimalField(max_digits=12, decimal_places=2,default=0.00)

    

    class Meta:
        model = UserLevel
        fields = ['id', 'level_name', 'amount', 'is_active', 'status', 'pay_enabled', 'linked_user_id', 'balance', 'received','is_upline_fully_paid','can_pay_now', 'target']

    def get_is_upline_fully_paid(self, user_level_instance):
        """Checks if the upline for this level is fully paid (L1-L6)."""
        if user_level_instance.user.user_id.startswith('MASTER'):
            return True
        if user_level_instance.level.order > 6:
            return True # Dependency check is skipped for non-matrix levels

        upline_id = user_level_instance.linked_user_id
        # Call the helper function from models.py
        return check_upline_fully_paid(upline_id)
    
    def get_can_pay_now(self, user_level_instance):
        """Determines if the user is currently eligible to pay this level."""
        if user_level_instance.user.user_id.startswith('MASTER'):
            return True
        
        is_unpaid = user_level_instance.status != 'paid'
        upline_is_paid = self.get_is_upline_fully_paid(user_level_instance)
        is_matrix_level = user_level_instance.level.order <= 6
        
        # User can pay if: 1) Unpaid AND 2) Matrix Level AND 3) Upline is fully paid
        return is_unpaid and is_matrix_level and upline_is_paid
    
    def get_amount(self, obj):
        if obj.level:
            return obj.level.amount
        return Decimal('0.00')

    def get_level_name(self, obj):
        # The 'obj' here is the UserLevel instance.
        
        # 🟢 CRITICAL FIX: Check if the 'level' ForeignKey is not None
        if obj.level:
            return obj.level.name
        # 🟢 If it's None, return a default string instead of crashing
        return "Unassigned Level"

    # def get_amount(self, obj):
    #     try:
          
            
    #         last_payment = obj.payments.order_by('-id').first()
            
    #         if last_payment:
    #             return last_payment.amount
            
    #         # If no payment record exists, return 0.00 safely
    #         return Decimal('0.00')

    #     except AttributeError:
    #         # Catch the AttributeError if 'payments' (or whatever name you use) 
    #         # is somehow missing or not a manager.
    #         return Decimal('0.00')

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
    level_name = serializers.SerializerMethodField() 
    user_id = serializers.CharField(source='user.user_id')
    amount = serializers.SerializerMethodField() 
    payment_method = serializers.SerializerMethodField()
    transaction_id = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(allow_null=True)
    payment_proof_url = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    payment_id = serializers.SerializerMethodField()
    # ⭐ NEW FIELDS FOR LINKED USER ⭐
    linked_user_id = serializers.SerializerMethodField()
    linked_user_name = serializers.SerializerMethodField()
    class Meta:
        model = UserLevel
        fields = [ 'id','username', 'level_name', 'user_id', 'amount', 'payment_method', 'transaction_id', 
                  'status', 'approved_at', 'payment_proof_url', 'created_at', 'requested_date','payment_id','linked_user_id', 'linked_user_name']
    # --- New method to get the linked user's ID ---
    def get_linked_user_id(self, obj):
        # The ID is directly on the UserLevel model
        return getattr(obj, 'linked_user_id', None)

    # --- New method to get the linked user's FULL NAME ---
    def get_linked_user_name(self, obj):
        linked_user_id = self.get_linked_user_id(obj)
        if linked_user_id:
            try:
                # 2. Fetch the CustomUser object using the ID
                linked_user = CustomUser.objects.get(user_id=linked_user_id)
                # 3. Return the full name
                full_name = f"{getattr(linked_user, 'first_name', '')} {getattr(linked_user, 'last_name', '')}".strip()
                return full_name if full_name else linked_user_id # Fallback to ID if name is empty
            except CustomUser.DoesNotExist:
                return 'User Not Found'
        return 'N/A' # Or whatever default value you prefer    
    def get_username(self, obj):
        return f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip() or obj.user.user_id

    def get_level_name(self, obj):
        """Safely retrieves the level name."""
        return obj.level.name if obj.level else "MISSING LEVEL"

    def get_amount(self, obj):
        
        # Ensure Decimal is imported at the top of the file
        return obj.level.amount if obj.level else Decimal('0.00')

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

    def validate(self, data):
        user_level_id = data.get('user_level_id')
        request = self.context.get('request')
        user = request.user if request else None

        if not user:
            raise serializers.ValidationError({"error": "User context is required for payment initiation."})
        
        try:
            # 1. Fetch the UserLevel record
            # NOTE: Ensure UserLevel is imported at the top of serializers.py
            user_level_to_pay = UserLevel.objects.select_related('level').get(
                id=user_level_id, 
                user=user,
                status__in=['not_paid', 'rejected'] # Allow if not paid or rejected
            )
        except UserLevel.DoesNotExist:
            raise serializers.ValidationError({"user_level_id": "Invalid level ID, or level is already paid/pending/approved."})
        
        # 2. Extract key variables
        level_order = user_level_to_pay.level.order
        upline_id = user_level_to_pay.linked_user_id
        is_upline_master = upline_id.startswith('MASTER') if upline_id else False

        # 🛑 ENFORCEMENT LOGIC 
        if level_order >= 1 and level_order <= 6:
            # Check for linked user existence first
            if not is_upline_master and not check_upline_fully_paid(upline_id):
    
                upline_user = CustomUser.objects.get(user_id=upline_id)
                paid_levels_count = upline_user.userlevel_set.filter(
                    level__order__gte=1,
                    level__order__lte=6,
                    status='paid'
                ).count()
                
                # Raise the specific payment blocked error
                raise serializers.ValidationError({
                    "error": (f"Payment Blocked: Your upline ({upline_id}) has only paid for {paid_levels_count} "
                              f"levels (1-6) and must complete all levels before you can pay Level {level_order} manually.")
                })

        
        # Add the full UserLevel object to validated_data for easy access in the view
        data['user_level_instance'] = user_level_to_pay
        return data

class InitiatePaymentSerializer(serializers.Serializer):
    user_level_id = serializers.IntegerField()
    payment_method = serializers.ChoiceField(choices=['Razorpay', 'Manual'])

    def validate(self, data):
        user_level_id = data.get('user_level_id')
        request = self.context.get('request')
        user = request.user if request else None

        if not user:
            raise serializers.ValidationError({"error": "User context is required for payment initiation."})
        
        try:
            # 1. Fetch the UserLevel record
            user_level_to_pay = UserLevel.objects.select_related('level').get(
                id=user_level_id, 
                user=user,
                status__in=['not_paid', 'rejected'] # Allow payment if not paid or rejected
            )
        except UserLevel.DoesNotExist:
            raise serializers.ValidationError({"user_level_id": "Invalid level ID, or level is already paid/pending."})
        
        # 2. Extract key variables
        # level_order = user_level_to_pay.level.order
        # upline_id = user_level_to_pay.linked_user_id

        # # 🛑 ENFORCEMENT LOGIC 
        # if level_order >= 1 and level_order <= 6:
        #     # Check for linked user existence first
        #     if not upline_id:
        #         raise serializers.ValidationError({
        #             "error": "Cannot initiate payment: Upline slot is not yet assigned for this level."
        #         })
                
        #     # Use the helper function here
        #     if not check_upline_fully_paid(upline_id):
        #         raise serializers.ValidationError({
        #             "error": f"Payment Blocked: Your upline ({upline_id}) must complete payment for all levels (1-6) before you can pay Level {level_order}."
        #         })

        level_order = user_level_to_pay.level.order
        upline_id = user_level_to_pay.linked_user_id
        is_upline_master = upline_id.startswith('MASTER') if upline_id else False

        # 🛑 ENFORCEMENT LOGIC 
        if level_order >= 1 and level_order <= 6:
            # Check for linked user existence first
            if not is_upline_master and not check_upline_fully_paid(upline_id):
    
                upline_user = CustomUser.objects.get(user_id=upline_id)
                paid_levels_count = upline_user.userlevel_set.filter(
                    level__order__gte=1,
                    level__order__lte=6,
                    status='paid'
                ).count()
                
                # Raise the specific payment blocked error
                raise serializers.ValidationError({
                    "error": (f"Payment Blocked: Your upline ({upline_id}) has only paid for {paid_levels_count} "
                              f"levels (1-6) and must complete all levels before you can pay Level {level_order} manually.")
                })

        
        
        # Add the full UserLevel object to validated_data for easy access in the view
        data['user_level_instance'] = user_level_to_pay
        return data



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
    payer_email = serializers.CharField(source='user.email', read_only=True)
    payer_full_name = serializers.SerializerMethodField()

    class Meta:
        model = UserLevel
        fields = ('id', 'payer_user_id', 'payer_name', 'level_name', 'requested_date', 'status', 'payer_email', 'payer_full_name')

    def get_payer_full_name(self, obj):
        user = obj.user
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        return full_name if full_name else user.user_id

    


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
    
    

                            

class AdminMasterUserSerializer(serializers.ModelSerializer):
    # Fields pulled directly from the CustomUser model (the source object)
    user_id = serializers.CharField(max_length=20, read_only=True)
    first_name = serializers.CharField(max_length=100, read_only=True)
    last_name = serializers.CharField(max_length=100, read_only=True)

    email = serializers.EmailField(read_only=True)
    mobile = serializers.CharField(read_only=True)
    whatsapp_number = serializers.CharField(read_only=True)
    pincode = serializers.CharField(read_only=True)
    upi_number = serializers.CharField(read_only=True)
    sponsor_id = serializers.CharField(read_only=True) 
    placement_id = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True) # Global CustomUser active status
    
    # Custom fields derived by aggregation from the related UserLevel records
    admin_level_linked = serializers.SerializerMethodField()
    current_status_display = serializers.SerializerMethodField()
    linked_user_id = serializers.SerializerMethodField()
    node_type = serializers.SerializerMethodField() 
    total_income = serializers.SerializerMethodField() # Calculated total income

    class Meta:
        model = CustomUser # <--- CRITICAL CHANGE: Base model is CustomUser
        fields = (
            'user_id', 'first_name', 'last_name','email', 'pk', 'admin_level_linked', 
            'current_status_display', 'linked_user_id', 'is_active', 'node_type', 
            'total_income', 'mobile', 'whatsapp_number', 'pincode', 'upi_number', 
            'sponsor_id', 'placement_id'
        )
        read_only_fields = fields

    # --- Aggregation Logic ---

    def get_admin_level_linked(self, user):
        """
        Finds which of the Admin's matrix slots (Levels 1-6) this dummy user is linked to.
        This provides the single Admin level link to display on the user's record.
        """

        try:
           
            admin_user_id = self.context.get('admin_user_id')
            
            if not admin_user_id and self.context.get('request') and self.context['request'].user.is_authenticated:
                admin_user_id = self.context['request'].user.user_id
            
            if not admin_user_id:
                # Cannot proceed without the Admin ID
                return "Error: Admin ID Missing"

            # 2. Fetch the Admin's CustomUser object explicitly
            # This guarantees we query the database with the correct user instance.
            admin_user = CustomUser.objects.get(user_id=admin_user_id) 
            
            # 3. Perform the query using the fetched Admin user object
            linked_slot = UserLevel.objects.using('default').filter( # <-- ADDED .using('default')
                user=admin_user, 
                linked_user_id=user.user_id,
                level__order__lte=6 
            ).select_related('level').first()
                
            return linked_slot.level.name if linked_slot else "Not Linked"
        except:
            return "Error/Not Linked"

    def get_current_status_display(self, user):
        """
        Checks the global CustomUser status and aggregates the UserLevel payment status.
        If the user is globally active, but ANY critical level is unpaid/pending, they are "Payment Pending".
        """
        if not user.is_active:
            return "INACTIVE (Admin Disabled)"

        # Check for any unpaid/pending status among the critical matrix levels (1-6)
        unpaid_levels_exist = user.userlevel_set.filter(
            level__order__lte=6, 
            status__in=['not_paid', 'pending']
        ).exists()
        
        if unpaid_levels_exist:
            return "ACTIVE (Payment Pending)"
            
        # If active and no critical levels are unpaid, assume full payment
        return "ACTIVE (Paid)" 
        
    def get_total_income(self, user):
        """
        Sums up the received income across all UserLevel records for this user.
        """
        # Using aggregation to sum the 'received' field from the related manager
        total = user.userlevel_set.aggregate(total_received=Sum('received'))
        # Assuming 'received' is the field for total income in the UserLevel model
        return total['total_received'] if total['total_received'] is not None else 0.0
        
    def get_node_type(self, user):
        """
        Determines the node type based on the CustomUser's user_id.
        """
        if user.user_id.startswith('MASTER'):
            return "MASTER Node"
        elif user.user_id.startswith('DUMMY'):
            return "OLD Dummy Data"
        return "Unknown Node Type"

    def get_linked_user_id(self, user):
        """
        Returns the linked_user_id (upline) for the user's primary level (Level 1).
        This is typically the original placement on the Admin's Master Node chain.
        """
        level_one = user.userlevel_set.filter(level__order=1).first()
        return level_one.linked_user_id if level_one else "N/A"

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
        if assigned_level:
            user_level, created = UserLevel.objects.update_or_create(
                # CRITICAL: Fields used to FIND the record (unique constraint fields)
                user=user,
                level=assigned_level,
                defaults={
                    # Fields to SET/UPDATE on creation or existing record
                    'linked_user_id': admin.user_id, # Linking the admin as the upline
                    'is_active': can_be_active,
                    'payment_mode': validated_data['select_payment_type'], 
                    'status': 'paid', # New users start as not_paid
                    'received': Decimal('0.00'), 
                }
            )
        else:
            # Handle case where no assigned_level was found (e.g., admin slots full)
            # The user is created but remains unlinked, and this view returns an error
            # or a specific instance if you need one to pass to the response serializer.
            # For now, we'll return a placeholder or the CustomUser instance itself.
            user_level = None 
            # NOTE: You might need to change your view logic if user_level is None here.
            # A common approach is to return the newly created `user` object.
            
        

   
        # 6. Link Admin's slot
        if assigned_level:
            UserLevel.objects.filter(user=admin, level=assigned_level).update(linked_user_id=user.user_id)

        return user 




# --- 3. AdminDummyUserUpdateSerializer (Multi-Model Update/PATCH) ---
class AdminDummyUserUpdateSerializer(serializers.ModelSerializer):
    # CRITICAL CHANGE: Inherit from ModelSerializer and set model to CustomUser
    
    # Fields pulled directly from CustomUser
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    mobile = serializers.CharField(max_length=15, required=False)
    is_active = serializers.BooleanField(required=False)
    whatsapp_number = serializers.CharField(max_length=15, required=False)
    pincode = serializers.CharField(max_length=10, required=False)
    upi_number = serializers.CharField(max_length=50, required=False)
    
    # Fields that belong to UserLevel, handled manually in update()
    level = serializers.PrimaryKeyRelatedField(queryset=Level.objects.all(), required=False, write_only=True)
    status = serializers.ChoiceField(
        choices=[('not_paid', 'Not Paid'), ('paid', 'Paid'), ('pending', 'Pending'), ('rejected', 'Rejected')],
        required=False, write_only=True
    )
    
    # Read-only fields (from CustomUser)
    user_id = serializers.CharField(read_only=True)
    pk = serializers.IntegerField(read_only=True)
    
    # Read-only fields derived from context/relationships
    linked_user_id = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser # CRITICAL CHANGE
        fields = (
            'first_name', 'last_name', 'email', 'mobile', 'is_active', 'whatsapp_number', 
            'pincode', 'upi_number', 'user_id', 'pk', 'linked_user_id', 'level', 'status'
        )
        # Note: 'level' and 'status' are marked write_only, as they belong to UserLevel

    def get_linked_user_id(self, user):
        # Displays the upline user ID for Level 1 (for context)
        level_one = user.userlevel_set.filter(level__order=1).first()
        return level_one.linked_user_id if level_one else None

    def validate(self, data):
        instance = self.instance # instance is now CustomUser
        
        # 🟢 Logic remains the same, fields are accessed directly on instance
        if 'level' in data and not instance.is_active: # No need for instance.user.is_active
            raise serializers.ValidationError({"level": "Cannot change the level of an inactive dummy user. Activate the user first."})

        # 2. 6-Slot Activation Check (Simplified)
        if 'is_active' in data and data['is_active'] is True and instance.is_active is False:
            active_master_count_global = CustomUser.objects.filter(
                Q(user_id__startswith='MASTER'),
                is_active=True
            ).count()
            
            new_total_active = active_master_count_global + 1
            
            if new_total_active > 6:
                error_message = f"Activation failed. The maximum limit of 6 active dummy users has been reached. Current active count: {active_master_count_global}."
                raise serializers.ValidationError({"is_active": error_message})
                
        # 3. Email uniqueness check (Logic remains the same)
        if 'email' in data and data['email'] != instance.email:
            if CustomUser.objects.filter(email=data['email']).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError({"email": "This email is already in use by another user."})
            
        return data
 
    @transaction.atomic
    def update(self, instance, validated_data):
        original_user_active_status = instance.is_active
        new_active_status = validated_data.get('is_active')
        new_level = validated_data.pop('level', None)
        new_status = validated_data.pop('status', None)
        admin = self.context['request'].user
        moving_dummy_user_id = instance.user_id

        # PART 1: Update CustomUser data
        instance = super().update(instance, validated_data)

        # PART 2: Handle UserLevel updates (Status, is_active sync)

        # A. Sync is_active status globally across all UserLevel records
        if new_active_status is not None:
            UserLevel.objects.filter(user=instance).update(is_active=new_active_status)
                
        # B. Propagate status update
        if new_status:
            UserLevel.objects.filter(user=instance).update(
                status=new_status,
                approved_at=timezone.now() if new_status == 'paid' else None
            )

        # PART 3: Handle Level Change Logic (Manual Admin Placement)
        if new_level and instance.is_active:
            
            # 1. Check if the target slot exists
            admin_new_level_slot = UserLevel.objects.filter(user=admin, level=new_level).first()
            
            if not admin_new_level_slot:
                raise serializers.ValidationError({"level": f"Admin's UserLevel slot for {new_level.name} does not exist."})

            # 2. Check for occupation by another user (Prevents overwriting another active master node)
            overwritten_user_id = admin_new_level_slot.linked_user_id
            
            if overwritten_user_id and overwritten_user_id != moving_dummy_user_id:
                raise serializers.ValidationError({
                    "level": f"Slot for {new_level.name} is occupied by {overwritten_user_id}. Change is blocked."
                })
                
            # 3. Unconditionally free up the old slot(s) for this user (Prevents double-linking)
            UserLevel.objects.filter(
                user=admin, 
                linked_user_id=moving_dummy_user_id, 
                level__order__lte=6
            ).update(linked_user_id=None)
            
            # 4. Establish the new link (Occupy the new slot)
            UserLevel.objects.filter(user=admin, level=new_level).update(linked_user_id=moving_dummy_user_id)

        # PART 4: Handle Automatic Slot Linking/Unlinking (ONLY if no manual level change occurred)
        if new_active_status is not None and not new_level:
            
            if new_active_status is True and original_user_active_status is False:
                # Activation: Link to the next available slot if one exists
                if not UserLevel.objects.filter(user=admin, level__order__lt=7, linked_user_id=moving_dummy_user_id).exists():
                    available_slot = UserLevel.objects.filter(
                        user=admin, level__order__lt=7, linked_user_id__isnull=True
                    ).order_by('level__order').first()
                    
                    if available_slot:
                        UserLevel.objects.filter(pk=available_slot.pk).update(linked_user_id=moving_dummy_user_id)

            elif new_active_status is False and original_user_active_status is True:
                # Deactivation: Unlink this dummy user from the Admin's slot(s)
                UserLevel.objects.filter(user=admin, linked_user_id=moving_dummy_user_id).update(linked_user_id=None)
                
        return instance

class PmfOrderSerializer(serializers.Serializer):
    """Used to initiate a PMF Razorpay order."""
    pmf_part = serializers.ChoiceField(
        choices=['part_1', 'part_2'],
        required=True,
        error_messages={'invalid_choice': 'Invalid PMF part. Must be "part_1" or "part_2".'}
    )

class PmfVerifySerializer(serializers.Serializer):
    """Used to verify PMF payment success."""
    # These fields are expected from the Razorpay callback/frontend confirmation
    razorpay_order_id = serializers.CharField(max_length=255, required=True)
    razorpay_payment_id = serializers.CharField(max_length=255, required=True)
    razorpay_signature = serializers.CharField(max_length=255, required=True)

class PmfManualPaymentSerializer(serializers.Serializer):
    pmf_part = serializers.ChoiceField(
        choices=['part_1', 'part_2'],
        required=True,
        error_messages={'invalid_choice': 'Invalid PMF part. Must be "part_1" or "part_2".'}
    )
    payment_proof = serializers.FileField(required=False, allow_null=True) 

class PmfPaymentSerializer(serializers.ModelSerializer):
    # Use pmf_type as the level/part name
    pmf_part_name = serializers.CharField(source='get_pmf_type_display', read_only=True)
    payment_proof = serializers.FileField(required=False, allow_null=True) 
    sender_user_id = serializers.CharField(source='user.user_id', read_only=True)

    sender_full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = PmfPayment
        # Minimal data for general listing/detail
        fields = ['id', 'user', 'pmf_part_name', 'status', 'created_at','payment_method','payment_proof', 'sender_user_id', 'sender_full_name']
        read_only_fields = fields 

    def get_sender_full_name(self, obj):
        return f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip() or obj.user.user_id

class AdminPendingPmfPaymentsSerializer(serializers.ModelSerializer):
    """
    Serializer for admin to view pending manual payments.
    Only shows ID, User ID, PMF Part Name, and Proof.
    """
    # Use pmf_type to display the Part Name (e.g., "PMF Part 1 Fee")
    level_name = serializers.CharField(source='get_pmf_type_display', read_only=True)
    
    # Get the user's main identifier (assuming user_id is the key identifier)
    user_id = serializers.CharField(source='user.user_id', read_only=True) 

    class Meta:
        model = PmfPayment
        fields = [
            'id', 
            'user_id', 
            'level_name', 
            'payment_method',
            'payment_proof', # The actual proof string/URL for review
        ]