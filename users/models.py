import random, string
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)

        # Generate unique DM ID
        user.user_id = self.generate_dm_id()
        user.save(using=self._db)
        return user

    def generate_dm_id(self):
        """
        Generate a random DM ID, ensure uniqueness
        """
        while True:
            rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            new_id = f"DM{rand_part}"
            if not self.model.objects.filter(user_id=new_id).exists():
                return new_id


class CustomUser(AbstractBaseUser, PermissionsMixin):
    PAYMENT_CHOICES = [
        ("GPay", "GPay"),
        ("PhonePe", "PhonePe"),
        ("CredPay", "CredPay"),
    ]
    
    user_id = models.CharField(max_length=20, unique=True, editable=False)

    sponsor_name = models.CharField(max_length=255, blank=True, null=True)
    placement_id = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=10)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_CHOICES)
    upi_number = models.CharField(max_length=50)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=15, unique=True)
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=100)

     # Referral system
    referred_by = models.ForeignKey(
        "self",
        related_name="referrals",
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )

    # Auth required fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'user_id'  # Login using DM ID
    REQUIRED_FIELDS = ['email']

    objects = CustomUserManager()

    def __str__(self):
        return self.user_id
    
class PasswordResetToken(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="reset_tokens")
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def is_valid(self):
        return timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=15)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.user_id} - {self.token}"