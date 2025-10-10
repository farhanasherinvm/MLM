import logging
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal
from users.models import CustomUser
from profiles.models import Profile
from django.db.models import F
import json
import uuid
from django.utils import timezone
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.conf import settings

logger = logging.getLogger(__name__)

class Level(models.Model):
    name = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    order = models.IntegerField(default=0, unique=True)

    def __str__(self):
        return self.name

    @classmethod
    def create_default_levels(cls):
        levels_data = [
            {'name': 'Level 1', 'amount': 100, 'order': 1},
            {'name': 'Level 2', 'amount': 125, 'order': 2},
            {'name': 'Level 3', 'amount': 150, 'order': 3},
            {'name': 'Level 4', 'amount': 175, 'order': 4},
            {'name': 'Level 5', 'amount': 200, 'order': 5},
            {'name': 'Level 6', 'amount': 950, 'order': 6},
            {'name': 'Refer Help', 'amount': 500, 'order': 7},
        ]
        for data in levels_data:
            # Use 'name' for lookup (the unique identifier)
            lookup_key = data['name']
            
            # Use the other fields for updates/defaults
            defaults_data = {
                'amount': data['amount'],
                'order': data['order']
            }
            
            level, created = cls.objects.update_or_create(
                name=lookup_key,
                defaults=defaults_data
            )

class UserLevel(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    level = models.ForeignKey(Level, on_delete=models.CASCADE, null=True , blank=True)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, null=True, blank=True)
    linked_user_id = models.CharField(max_length=20, null=True, blank=True, default=None)
    is_active = models.BooleanField(default=True)
    payment_mode = models.CharField(max_length=50, default='Manual', blank=True)
    transaction_id = models.CharField(max_length=100, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    requested_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('not_paid', 'Not Paid'),
            ('paid', 'Paid'),
            ('pending', 'Pending'),
            ('rejected', 'Rejected')
        ],
        default='not_paid'
    )
    pay_enabled = models.BooleanField(default=True)
    target = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    received = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        unique_together = ('user', 'level')
        ordering = ['level__order']

    def __str__(self):
        level_name = self.level.name if self.level else "No Level Assigned"
        user_id = self.user.user_id if self.user else "No User ID" 
        return f"{user_id} - {level_name}"


    def save(self, *args, **kwargs):
        if self.pk:  # Check if the instance already exists
            original = UserLevel.objects.get(pk=self.pk)
            if original.status != self.status:
                self.requested_date = timezone.now()
        super().save(*args, **kwargs) 

class LevelPayment(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Verified", "Verified"),
        ("Failed", "Failed"),
        ('Restricted', 'Payment On Hold - Cap Reached')
    ]
    PAYMENT_METHOD_CHOICES = [
        ("Razorpay", "Razorpay"),
        ("Manual", "Manual"),
    ]

    payment_token = models.UUIDField(default=uuid.uuid4, unique=True)
    user_level = models.ForeignKey(UserLevel, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="Pending")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default="Manual")
    razorpay_order_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    payment_proof = models.FileField(upload_to='payment_proofs/', storage=MediaCloudinaryStorage(), null=True, blank=True)
    payment_data = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_payment_data(self, data):
        """Set payment_data as JSON string without saving."""
        if not isinstance(data, dict):
            raise ValueError("Data must be a dictionary")
        try:
            self.payment_data = json.dumps(data)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid data format: {str(e)}")

    def get_payment_data(self):
        """Retrieve payment_data as a dictionary."""
        if self.payment_data:
            try:
                return json.loads(self.payment_data)
            except json.JSONDecodeError as e:
                return {}
        return {}

    def __str__(self):
        return f"LevelPayment {self.id} - {self.user_level} - {self.status}"

class PmfPayment(models.Model):
    PMF_TYPE_CHOICES = [
        ("PMF_PART_1", "PMF Part 1 Fee"),
        ("PMF_PART_2", "PMF Part 2 Fee"),
    ]
    PAYMENT_STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Verified", "Verified"),
        ("Failed", "Failed"),
    ]
    PAYMENT_METHOD_CHOICES = [
        ("Razorpay", "Razorpay"),
        ("Manual", "Manual"),
    ]

    # Link to the user who owes the fee (using settings.AUTH_USER_MODEL)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='pmf_payments'
    )
    payment_method = models.CharField(
        max_length=20, 
        choices=PAYMENT_METHOD_CHOICES, 
        default="Razorpay" # <--- This ensures the default is Razorpay
    )
    
    # Identify which PMF part this record represents
    pmf_type = models.CharField(max_length=20, choices=PMF_TYPE_CHOICES)
    payment_proof = models.CharField(max_length=500, blank=True, null=True)

    
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=1000.00)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="Pending")

    # Razorpay fields
    razorpay_order_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PMF Payment {self.id} - {self.user.user_id} - {self.pmf_type}"

def get_upline(user, depth):
    """Get the upline user at the specified depth."""
    current = user
    for _ in range(depth):
        if not current or not current.placement_id:
            return None
        try:
            current = CustomUser.objects.get(user_id=current.placement_id)
        except CustomUser.DoesNotExist:
            return None
    return current

def check_upline_fully_paid(upline_id):
    """
    Checks if the upline user identified by upline_id has paid ALL levels 1-6.
    Returns True only if the upline is fully paid for L1-L6.
    """
    if not upline_id:
        return False
    
    try:
        
        
        upline_user = CustomUser.objects.get(user_id=upline_id)
    except CustomUser.DoesNotExist:
        # If the upline doesn't exist, block payment/show ineligible.
        logger.error(f"Upline user {upline_id} not found for payment check.")
        return False

    # Check the count of paid levels (L1-L6) for the upline.
    paid_levels_count = upline_user.userlevel_set.filter(
        level__order__gte=1,
        level__order__lte=6,
        status='paid'
    ).count()
    
    # The upline must have paid ALL 6 matrix levels
    return paid_levels_count >= 6

def get_referrer_details(linked_user_id):
    """
    Fetch referrer details from linked_user_id (CustomUser.user_id).
    Returns dict with user details from Profile.
    """
    if not linked_user_id:
        return None
    try:
        referrer_user = CustomUser.objects.get(user_id=linked_user_id)
        referrer_profile = referrer_user.profile
        return {
            'user_id': linked_user_id,
            'username': f"{referrer_user.first_name} {referrer_user.last_name}".strip(),
            'name': f"{referrer_profile.first_name} {referrer_profile.last_name}".strip(),
            'email': referrer_user.email,
            'mobile': referrer_user.mobile,
            'whatsapp_number': referrer_user.whatsapp_number or '',
        }
    except (CustomUser.DoesNotExist, Profile.DoesNotExist):
        return None

@receiver(post_save, sender=CustomUser)
def create_user_levels(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Signal triggered for user {instance.user_id}, created={created}")
        try:
            with transaction.atomic():
                levels = Level.objects.all().order_by('order')
                if not levels.exists():
                    logger.error(f"No Level objects found for user {instance.user_id}")
                    raise Exception("No Level objects available")

                sponsor_id = instance.sponsor_id
                logger.debug(f"Sponsor ID: {sponsor_id} for user {instance.user_id}")

                referrer = None
                if sponsor_id and CustomUser.objects.filter(user_id=sponsor_id).exists():
                    referrer = CustomUser.objects.get(user_id=sponsor_id)
                else:
                    logger.warning(f"No valid sponsor_id for user {instance.user_id}")

                admin_user = None
                # Fetch Admin ID from settings (You must define ADMIN_USER_ID in settings.py)
                admin_user_id = getattr(settings, 'ADMIN_USER_ID', None) 

                if admin_user_id:
                    try:
                        admin_user = CustomUser.objects.get(user_id=admin_user_id)
                    except CustomUser.DoesNotExist:
                        logger.error(f"Admin User with ID {admin_user_id} not found. 'Refer Help' linking may fail.")
                
                # The primary recipient is the referrer. If referrer is None, use the admin_user.
                refer_help_recipient = referrer if referrer else admin_user

                for level in levels:
                    linked_user_id = None
                    upline_user = None
                    # Logic for Levels 1-6 (Nth upline)
                    # if 1 <= level.order <= 6:
                    #     depth = level.order  
                    #     upline_user = get_upline(instance, depth)  
                        
                    #     if upline_user:
                    #         linked_user_id = upline_user.user_id
                    if 1 <= level.order <= 6:
                        depth = level.order
                        
                        # A. Try Placement Chain First
                        if instance.placement_id:
                            upline_user = get_upline(instance, depth) 
                        
                        # B. If Placement Fails or is Missing, Try Dummy Upline
                        if not upline_user:
                            try:
                                # 🟢 CORRECTED DUMMY USER LOGIC: Filter by user_id prefix
                                upline_user = CustomUser.objects.filter(
                                    user_id__startswith='MASTER', # <-- CHANGED FILTER
                                    is_active=True 
                                ).order_by('user_id')[depth - 1] # Order by user_id to ensure a stable chain
                            except IndexError:
                                # No more active dummy users found at this depth
                                upline_user = None
                        # C. Final Assignment (Sets linked_user_id to the found ID or None)
                        
                        linked_user_id = upline_user.user_id if upline_user else None
                            
                        # C. Set ID based on the result
                        
                    
                    # Logic for 'Refer Help' (linking to direct sponsor)
                    elif level.name == 'Refer Help':
                        if refer_help_recipient:
                            # Use the determined recipient (Sponsor or Admin)
                            linked_user_id = refer_help_recipient.user_id

                    profile = Profile.objects.filter(user=instance).first()
                    target = level.amount * (Decimal('2') ** level.order)
                    
                    if level.name == 'Refer Help':
                         target = level.amount 
                         balance = level.amount

                    user_level, created = UserLevel.objects.get_or_create(
                        user=instance,
                        level=level,
                        defaults={
                            'profile': profile,
                            'linked_user_id': linked_user_id,
                            'status': 'not_paid',
                            'payment_mode': 'Manual',
                            'target': target,
                            'balance': target,
                            'received': 0
                        }
                    )
                    if not created:
                        logger.warning(f"UserLevel already exists for {instance.user_id} - {level.name}, skipping creation")
                    else:
                        logger.debug(f"UserLevel created={created} for {instance.user_id} - {level.name}")

                    # The logic to create/update a 'Refer Help' level for the REFERRER
                    if referrer and level.name == 'Refer Help':
                        refer_help_ulevel, created_referrer_level = UserLevel.objects.get_or_create(
                            user=refer_help_recipient,
                            level=level,
                            defaults={
                                'linked_user_id': None,
                                'status': 'not_paid',
                                'payment_mode': 'Manual',
                                'target': level.amount,
                                'balance': level.amount,
                                'received': 0
                            }
                        )
                        # This part seems designed to link the REFERRER's Refer Help level to the NEW USER
                        # if it doesn't already have a linked user. This is an unusual MLM structure.
                        # I've kept the original logic here.
                        if not refer_help_ulevel.linked_user_id:
                            refer_help_ulevel.linked_user_id = instance.user_id
                            refer_help_ulevel.save()
                            logger.debug(f"Updated Refer Help linked_user_id for {referrer.user_id} to {instance.user_id}")

                if referrer:
                    profile = Profile.objects.filter(user=referrer).first()
                    if profile:
                        user_levels = UserLevel.objects.filter(user=referrer)
                        if user_levels.exclude(status='paid').count() == 0:
                            profile.eligible_to_refer = True
                            profile.save()
                            logger.debug(f"Set eligible_to_refer=True for {referrer.user_id}")

            logger.info(f"Successfully created UserLevel records for user {instance.user_id}")
        except Exception as e:
            logger.error(f"Failed to create UserLevel records for {instance.user_id}: {str(e)}")
            raise


@receiver(post_save, sender=Level)
def update_user_levels_on_amount_change(sender, instance, **kwargs):
    if instance.pk and instance.name != 'Refer Help':
        try:
            old_level = Level.objects.get(pk=instance.pk)
            if old_level.amount != instance.amount:
                target_multiplier = Decimal('2') ** instance.order
                new_target = instance.amount * target_multiplier
                UserLevel.objects.filter(level=instance).update(
                    target=new_target,
                    balance=Decimal('0')
                )
                UserLevel.objects.filter(level=instance, status='paid').update(
                    balance=new_target
                )
                logger.debug(f"Updated target to {new_target} and balance for Level {instance.name}")
        except Level.DoesNotExist:
            pass

@receiver(post_save, sender=UserLevel)
def update_related_user_levels(sender, instance, created, **kwargs):
    if instance.level is None:
        logger.warning(f"UserLevel {instance.pk} has no assigned level; skipping signal processing.")
        return
    if not created and instance.status == 'paid' and instance.linked_user_id:
        with transaction.atomic():
            try:
                linked_user = CustomUser.objects.get(user_id=instance.linked_user_id)
                linked_ulevel = UserLevel.objects.get(user=linked_user, level=instance.level)
                
                amount = instance.level.amount
                if linked_ulevel.balance >= amount:
                    UserLevel.objects.filter(id=linked_ulevel.id).update(
                        received=F('received') + amount,
                        balance=F('balance') - amount
                    )
                    logger.debug(f"Updated linked user {linked_user.user_id} - received: {amount}, balance adjusted")
                else:
                    logger.warning(f"Insufficient balance for linked user {linked_user.user_id}")
            except (CustomUser.DoesNotExist, UserLevel.DoesNotExist):
                logger.error(f"Linked user or UserLevel not found for {instance.linked_user_id}")

            if instance.level.order < 7:
                next_level = Level.objects.filter(order=instance.level.order + 1).first()
                if next_level:
                    next_user_level = UserLevel.objects.get(user=instance.user, level=next_level)
                    UserLevel.objects.filter(id=next_user_level.id).update(
                        is_active=True,
                        pay_enabled=True
                    )

@receiver(post_save, sender=LevelPayment)
def update_user_level_on_payment(sender, instance, created, **kwargs):
    if instance.status == "Verified":
        with transaction.atomic():
            user_level = instance.user_level
            if user_level.status != 'paid': 
                user_level.status = 'paid'
                user_level.payment_mode = 'Razorpay'
                user_level.approved_at = timezone.now()
                user_level.transaction_id = instance.razorpay_payment_id
                user_level.save() 
                logger.info(f"UserLevel {user_level.id} marked as paid due to LevelPayment {instance.id} verification")
                
                user_levels = UserLevel.objects.filter(user=user_level.user)
                if user_levels.filter(status='paid').count() == user_levels.count():
                    try:
                        profile = Profile.objects.get(user=user_level.user)
                        profile.eligible_to_refer = True
                        profile.save()
                        logger.debug(f"Set eligible_to_refer=True for {user_level.user.user_id}")
                    except Profile.DoesNotExist:
                        logger.warning(f"No Profile found for user {user_level.user.user_id} when enabling referring")


