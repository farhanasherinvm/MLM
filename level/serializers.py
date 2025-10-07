from rest_framework import serializers
from .models import Level, UserLevel, LevelPayment, get_referrer_details
import logging
from users.models import CustomUser
from django.utils import timezone
from profiles.models import Profile
from django.conf import settings
import random
import uuid
from django.db import transaction
import string
from django.db.models import Q

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
    
    def get_admin_level_linked(self, obj):
        return obj.level.name if obj.level else "N/A"

    def get_current_status_display(self, obj):
        if not obj.is_active:
            return "INACTIVE (Admin Disabled)"
        if obj.status == 'not_paid':
            return "ACTIVE (Payment Pending)"
        return f"ACTIVE ({obj.status.replace('_', ' ').title()})"


# --- 2. Serializer for Creating Dummy Users (with Flexible Count & Limit Logic) ---
class CreateDummyUsersSerializer(serializers.Serializer):
    count = serializers.IntegerField(default=1, min_value=1)

    def get_unique_suffix(self, length=4):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def create(self, validated_data):
        admin = self.context['request'].user
        count = validated_data.get('count')
        dummy_users_data = []

        # --- FIX: Robust ID Generation Logic ---
        
        # 1. Filter all users with dummy prefixes ('DUMMY' or 'FAKEDATA')
        all_dummy_users = CustomUser.objects.filter(
            Q(user_id__startswith='DUMMY') | Q(user_id__startswith='FAKEDATA')
        ).values_list('user_id', flat=True)
        
        highest_numeric_id = 0
        
        for user_id in all_dummy_users:
            try:
                # Remove the prefix (DUMMY or FAKEDATA) and any suffix (like _a1c3)
                if user_id.startswith('DUMMY'):
                    numeric_part = user_id.replace('DUMMY', '')
                elif user_id.startswith('FAKEDATA'):
                    numeric_part = user_id.replace('FAKEDATA', '')
                else:
                    continue # Skip if it doesn't match expected prefixes

                # Strip off any non-digit characters that might follow the number (e.g., '_')
                numeric_part = ''.join(filter(str.isdigit, numeric_part))
                
                if numeric_part:
                    current_id = int(numeric_part)
                    if current_id > highest_numeric_id:
                        highest_numeric_id = current_id
            except ValueError:
                # Ignore non-standard IDs (if any exist)
                continue
        
        # The next ID number is one greater than the highest found
        start_id = highest_numeric_id + 1
        # --- END FIX ---

        user_ids = []
        emails = []
        mobiles = []

        for i in range(count):
            current_id_num = start_id + i
            suffix = self.get_unique_suffix() 

            new_user_id = f'DUMMY{current_id_num:04d}' 
            user_ids.append(new_user_id)
            emails.append(f'testuser_{suffix}_{current_id_num}@dummycorp.com')
            mobiles.append(''.join(random.choices('789', k=1) + random.choices('0123456789', k=9)))


        # Get Admin Levels and Active Slot Counts
        admin_levels_queryset = UserLevel.objects.filter(user=admin).exclude(level__name='Refer Help').order_by('level__order')
        admin_user_levels = list(admin_levels_queryset)
        
        if not admin_user_levels:
             raise serializers.ValidationError({"error": "Admin must have existing UserLevels (1-6) to link the dummy users."})

        # active_dummy_count = UserLevel.objects.filter(
        #     (Q(user__user_id__startswith='DUMMY') | Q(user__user_id__startswith='FAKEDATA')), 
        #     is_active=True
        # ).count()
        active_dummy_count = admin_levels_queryset.exclude(linked_user_id__isnull=True).exclude(linked_user_id__exact='').count()
        slots_available = 6 - active_dummy_count
        
        # Determine which of the Admin's levels are currently AVAILABLE (linked_user_id is None/empty)
        # This will be used to see if we should assign a dummy user's ID back to the admin's slot.
        available_admin_slots = {
            ul.level.pk: ul
            for ul in admin_user_levels
            if not ul.linked_user_id # Checks for empty/None linked_user_id
        }
        
        with transaction.atomic():
            # Bulk create CustomUser instances (same as before)
            new_users = [
                CustomUser(
                    user_id=user_ids[i],
                    first_name=f'DummyFirst{current_id_num}',
                    last_name=f'DummyLast{current_id_num}',
                    email=emails[i],
                    mobile=mobiles[i],
                    sponsor_id=admin.user_id,
                    is_active=True,
                    date_of_joining=timezone.now()
                ) for i, current_id_num in enumerate(range(start_id, start_id + count))
            ]

            CustomUser.objects.bulk_create(new_users)
            created_users = list(CustomUser.objects.filter(user_id__in=user_ids))

            new_user_levels = []
            admin_levels_to_link = {}

            for i, dummy_user in enumerate(created_users):
                should_be_active = (active_dummy_count + i) < 6
                
                assigned_level = None
                level_name = "Not Assigned"
                
                # Assign a level ONLY if a slot is available (should_be_active is True)
                if should_be_active:
                    # Circularly assign the active dummy users to the Admin's levels
                    level_index = (active_dummy_count + i) % len(admin_user_levels)
                    assigned_admin_level = admin_user_levels[level_index]
                    assigned_level = assigned_admin_level.level
                    level_name = assigned_level.name
                    
                    # Store the link, but only if the Admin's slot is currently empty/available
                    if assigned_level.pk in available_admin_slots:
                         admin_levels_to_link[assigned_level.pk] = dummy_user.user_id


                user_level = UserLevel(
                    user=dummy_user,
                    level=assigned_level, # This will be None if the 6-user limit is hit
                    linked_user_id=admin.user_id,
                    is_active=should_be_active,
                    payment_mode='Manual',
                    status='not_paid'
                )
                new_user_levels.append(user_level)

                dummy_users_data.append({
                    'user_id': dummy_user.user_id,
                    'first_name': dummy_user.first_name,
                    'last_name': dummy_user.last_name,
                    'email': dummy_user.email,
                    'mobile': dummy_user.mobile,
                    'sponsor_id': dummy_user.sponsor_id,
                    'level': level_name, # Display the name or 'Not Assigned'
                    'linked_user_id': user_level.linked_user_id,
                })

            UserLevel.objects.bulk_create(new_user_levels)
            
            # --- Update Admin's linked_user_id ONLY IF THE SLOT IS CURRENTLY EMPTY ---
            updates_for_admin_levels = []
            
            for admin_ul in admin_levels_queryset:
                linked_id = admin_levels_to_link.get(admin_ul.level.pk)
                
                # CHECK: Only update if we found a dummy ID to link AND the admin's slot is currently empty
                if linked_id and not admin_ul.linked_user_id:
                    admin_ul.linked_user_id = linked_id
                    updates_for_admin_levels.append(admin_ul)

            if updates_for_admin_levels:
                UserLevel.objects.bulk_update(
                    updates_for_admin_levels, 
                    fields=['linked_user_id']
                )

        return {'message': f"{len(dummy_users_data)} fake users created and linked to admin's levels", 'dummy_users': dummy_users_data}


# --- 3. Serializer for Admin Control (PATCH Endpoint) ---

class AdminDummyUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserLevel
        fields = ['is_active', 'level', 'linked_user_id']
        read_only_fields = ['user', 'payment_mode', 'status']

    def validate(self, data):
        instance = self.instance 
        
        admin = self.context['request'].user 

        # Check if the 'level' field is being updated
        if 'level' in data:
            if not instance.is_active:
                raise serializers.ValidationError({
                    "level": "Cannot change the level of an inactive dummy user. Activate the user first."
                })
        
       
        if 'is_active' in data and data['is_active'] is True and instance.is_active is False:
            
            occupied_slots_count = UserLevel.objects.filter(
                user=admin,  
                linked_user_id__isnull=False # Ensure linked_user_id is NOT NULL
            ).exclude(
                linked_user_id__exact=''    # Ensure linked_user_id is NOT an empty string
            ).count()
            
            # We check if the count is already 6 or more.
            if occupied_slots_count >= 6:
                raise serializers.ValidationError({
                    # 🌟 CORRECTION 3: Use the correct variable name in the error message.
                    "is_active": f"Activation failed. The maximum limit of 6 active dummy users has been reached (currently {occupied_slots_count} active)."
                })

        return data

    def update(self, instance, validated_data):
    # 1. Store the original level ID before the update
        original_level = instance.level 
        
        # 2. Get the new level ID from the validated data
        new_level_id = validated_data.get('level')
        
        # Use a transaction to ensure all updates succeed or all fail
        with transaction.atomic():
            # First, update the moving dummy user's UserLevel instance (e.g., set new level)
            updated_instance = super().update(instance, validated_data)
            
            # --- CUSTOM LOGIC TO SYNC ADMIN'S LEVELS AND HANDLE OVERWRITTEN USER ---
            
            # Check if the 'level' was actually changed and the moving user is active
            if new_level_id is not None and updated_instance.is_active and original_level and original_level.pk != new_level_id:
                
                admin = self.context['request'].user
                moving_dummy_user_id = updated_instance.user.user_id
                
                # --- STEP 1: Identify and Deactivate the Overwritten User (if any) ---
                
                # Find the admin's UserLevel record for the NEW level.
                admin_new_level_slot = UserLevel.objects.filter(
                    user=admin,
                    level_id=new_level_id 
                ).first()
                
                overwritten_user_id = None
                if admin_new_level_slot and admin_new_level_slot.linked_user_id:
                    overwritten_user_id = admin_new_level_slot.linked_user_id
                
                if overwritten_user_id:
                    # Find the overwritten dummy user's UserLevel record
                    # and remove their level/make them inactive.
                    UserLevel.objects.filter(
                        user__user_id=overwritten_user_id
                    ).update(
                        level=None, 
                        is_active=False # The user is now inactive and has no level
                    )

                # --- STEP 2: Unlink the moving dummy user from the Admin's OLD level slot ---
                
                UserLevel.objects.filter(
                    user=admin,
                    level=original_level,
                    linked_user_id=moving_dummy_user_id
                ).update(linked_user_id=None)
                
                # --- STEP 3: Link the moving dummy user to the Admin's NEW level slot ---
                
                # This query will either replace the 'overwritten_user_id' (if it existed)
                # or fill an empty slot with the 'moving_dummy_user_id'.
                UserLevel.objects.filter(
                    user=admin,
                    level_id=new_level_id 
                ).update(linked_user_id=moving_dummy_user_id)
                
            # --- END CUSTOM LOGIC ---
            
            return updated_instance