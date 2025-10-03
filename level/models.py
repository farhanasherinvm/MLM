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
            {'name': 'Level 2', 'amount': 200, 'order': 2},
            {'name': 'Level 3', 'amount': 400, 'order': 3},
            {'name': 'Level 4', 'amount': 1000, 'order': 4},
            {'name': 'Level 5', 'amount': 2000, 'order': 5},
            {'name': 'Level 6', 'amount': 5000, 'order': 6},
            {'name': 'Refer Help', 'amount': 1000, 'order': 7},
        ]
        for data in levels_data:
            level, created = cls.objects.get_or_create(**data)
            if created:
                logger.debug(f"Created default level: {data['name']}")

class UserLevel(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    level = models.ForeignKey(Level, on_delete=models.CASCADE)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, null=True, blank=True)
    linked_user_id = models.CharField(max_length=20, null=True, blank=True, default=None)
    is_active = models.BooleanField(default=True)
    payment_mode = models.CharField(max_length=50, default='Razorpay', blank=True)
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
        return f"{self.user.user_id} - {self.level.name}"


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
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default="Razorpay")
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

def get_upline(user, depth):
    """Get the upline user at the specified depth."""
    current = user
    for _ in range(depth):
        if not current or not current.sponsor_id:
            return None
        try:
            current = CustomUser.objects.get(user_id=current.sponsor_id)
        except CustomUser.DoesNotExist:
            return None
    return current

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
            'email': referrer_profile.email,
            'mobile': referrer_profile.mobile,
            'whatsapp_number': referrer_profile.whatsapp_number or '',
        }
    except (CustomUser.DoesNotExist, Profile.DoesNotExist):
        return None

@receiver(post_save, sender=CustomUser)
def create_user_levels(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Signal triggered for user {instance.user_id}, created={created}")
        try:
            with transaction.atomic():
                Level.create_default_levels()
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

                for level in levels:
                    linked_user_id = None
                    if referrer:
                        if level.order == 1:
                            linked_user_id = sponsor_id
                        elif 2 <= level.order <= 6:
                            prev_level = Level.objects.get(order=level.order - 1)
                            referrer_ulevel = UserLevel.objects.filter(user=referrer, level=prev_level).first()
                            if referrer_ulevel and referrer_ulevel.linked_user_id:
                                linked_user_id = referrer_ulevel.linked_user_id

                    profile = Profile.objects.filter(user=instance).first()
                    target = level.amount * (Decimal('2') ** level.order)
                    user_level, created = UserLevel.objects.get_or_create(
                        user=instance,
                        level=level,
                        defaults={
                            'profile': profile,
                            'linked_user_id': linked_user_id,
                            'status': 'not_paid',
                            'payment_mode': 'Razorpay',
                            'target': target,
                            'balance': target,
                            'received': 0
                        }
                    )
                    if not created:
                        logger.warning(f"UserLevel already exists for {instance.user_id} - {level.name}, skipping creation")
                    else:
                        logger.debug(f"UserLevel created={created} for {instance.user_id} - {level.name}")

                    if referrer and level.name == 'Refer Help':
                        refer_help_ulevel, _ = UserLevel.objects.get_or_create(
                            user=referrer,
                            level=level,
                            defaults={
                                'linked_user_id': None,
                                'status': 'not_paid',
                                'payment_mode': 'Razorpay',
                                'target': level.amount,
                                'balance': level.amount,
                                'received': 0
                            }
                        )
                        if not refer_help_ulevel.linked_user_id:
                            refer_help_ulevel.linked_user_id = instance.user_id
                            refer_help_ulevel.save()
                            logger.debug(f"Updated Refer Help linked_user_id for {referrer.user_id} to {instance.user_id}")

                if referrer:
                    profile = Profile.objects.filter(user=referrer).first()
                    if profile:
                        user_levels = UserLevel.objects.filter(user=referrer)
                        if user_levels.filter(status='paid').count() == user_levels.count():
                            profile.eligible_to_refer = True
                            profile.save()
                            logger.debug(f"Set eligible_to_refer=True for {referrer.user_id}")

            logger.info(f"Successfully created UserLevel records for user {instance.user_id}")
        except Exception as e:
            logger.error(f"Failed to create UserLevel records for {instance.user_id}: {str(e)}")
            raise

@receiver(post_save, sender=CustomUser)
def create_user_levels(sender, instance, created, **kwargs):
    if created:
        logger.debug(f"Signal triggered for user {instance.user_id}, created={created}")
        try:
            with transaction.atomic():
                Level.create_default_levels()
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

                for level in levels:
                    linked_user_id = None
                    if referrer and 1 <= level.order <= 6:
                        depth = level.order 
                        upline_user = get_upline(instance, depth) 
                        
                        if upline_user:
                            linked_user_id = upline_user.user_id

                    profile = Profile.objects.filter(user=instance).first()
                    target = level.amount * (Decimal('2') ** level.order)
                    user_level, created = UserLevel.objects.get_or_create(
                        user=instance,
                        level=level,
                        defaults={
                            'profile': profile,
                            'linked_user_id': linked_user_id,
                            'status': 'not_paid',
                            'payment_mode': 'Razorpay',
                            'target': target,
                            'balance': target,
                            'received': 0
                        }
                    )
                    if not created:
                        logger.warning(f"UserLevel already exists for {instance.user_id} - {level.name}, skipping creation")
                    else:
                        logger.debug(f"UserLevel created={created} for {instance.user_id} - {level.name}")

                    if referrer and level.name == 'Refer Help':
                        refer_help_ulevel, _ = UserLevel.objects.get_or_create(
                            user=referrer,
                            level=level,
                            defaults={
                                'linked_user_id': None,
                                'status': 'not_paid',
                                'payment_mode': 'Razorpay',
                                'target': level.amount,
                                'balance': level.amount,
                                'received': 0
                            }
                        )
                        if not refer_help_ulevel.linked_user_id:
                            refer_help_ulevel.linked_user_id = instance.user_id
                            refer_help_ulevel.save()
                            logger.debug(f"Updated Refer Help linked_user_id for {referrer.user_id} to {instance.user_id}")

                if referrer:
                    profile = Profile.objects.filter(user=referrer).first()
                    if profile:
                        user_levels = UserLevel.objects.filter(user=referrer)
                        if user_levels.filter(status='paid').count() == user_levels.count():
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