import os
import uuid
import random
from django.db import models
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.contrib.auth.models import (
    AbstractBaseUser, PermissionsMixin, BaseUserManager
)
import json
from django.utils import timezone
from django.conf import settings


PAYMENT_CHOICES = [
    ("GPay", "GPay"),
    ("PhonePe", "PhonePe"),
    ("PhonePay", "PhonePay"),
    ("Paytm", "Paytm"),
    ("Other", "Other"),
]

class CustomUserManager(BaseUserManager):
    def create_user(self, user_id, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(user_id=user_id, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, user_id, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_admin_user", True)
        return self.create_user(user_id, email, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    PAYMENT_CHOICES = [
    ("Razorpay", "Razorpay"),
    ("GPay", "GPay"),
    ("PhonePe", "PhonePe"),
    ("PhonePay", "PhonePay"),
    ("Paytm", "Paytm"),
    ("Other", "Other"),
    ]
    sponsor_id = models.CharField(max_length=255)
    placement_id = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)

    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=15, unique=True)

    whatsapp_number = models.CharField(max_length=15, null=True, blank=True, unique=True)
    pincode = models.CharField(max_length=10)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_CHOICES)
    upi_number = models.CharField(max_length=50)
    date_of_joining = models.DateTimeField(auto_now_add=True)

    user_id = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_admin_user = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = "user_id" 
    REQUIRED_FIELDS = ["email"]

    def __str__(self):
        return self.user_id
    
    @property
    def level(self):
        """
        Compute level based on referral chain.
        Level 1 → Direct referral from root/admin (or no sponsor)
        Level 2 → Referred by Level 1 user
        Level 3 → Referred by Level 2 user, etc.
        """
        level = 1
        sponsor_id = self.sponsor_id
        visited = set()  # avoid infinite loops
        while sponsor_id:
            if sponsor_id in visited:
                break
            visited.add(sponsor_id)
            try:
                sponsor = CustomUser.objects.get(user_id=sponsor_id)
                level += 1
                sponsor_id = sponsor.sponsor_id
            except CustomUser.DoesNotExist:
                break
        return level

    
class RegistrationRequest(models.Model):
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    sponsor_id = models.CharField(max_length=255)
    placement_id = models.CharField(max_length=255, blank=True, null=True)

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    email = models.EmailField()
    mobile = models.CharField(max_length=20)
    whatsapp_number = models.CharField(max_length=20, blank=True, null=True)
    pincode = models.CharField(max_length=10, blank=True, null=True)

    payment_type = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='razorpay')
    upi_number = models.CharField(max_length=100, blank=True, null=True)

    # store hashed password (use make_password before saving)
    password = models.CharField(max_length=255)

    amount = models.PositiveIntegerField(default=100)  # amount in INR, default non-editable in frontend

    created_at = models.DateTimeField(auto_now_add=True)
    is_completed = models.BooleanField(default=False)  # becomes True after user created

    def __str__(self):
        return f"RegistrationRequest({self.email})"


def receipt_upload_to(instance, filename):
    # store under media/payments/<registration_token>/
    return os.path.join('payments', str(instance.registration.token if instance.registration else 'unknown'), filename)


class Payment(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Verified", "Verified"),
        ("Failed", "Failed"),
    ]

    registration_token = models.UUIDField(default=uuid.uuid4, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="Pending")

    # Manual payment receipt
    receipt = models.FileField(upload_to="payments/", blank=True, null=True)

    # Store registration data as JSON string until verified
    registration_data = models.TextField(blank=True, null=True)

    # Razorpay fields
    razorpay_order_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)

    # Link to user once verified
    user = models.OneToOneField(CustomUser, on_delete=models.SET_NULL, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def set_registration_data(self, data: dict):
        self.registration_data = json.dumps(data)
        self.save()

    def get_registration_data(self):
        if self.registration_data:
            return json.loads(self.registration_data)
        return {}

    def __str__(self):
        return f"Payment {self.id} - {self.status}"
    
class AdminAccountDetails(models.Model):
    account_number = models.CharField(max_length=50)
    ifsc_code = models.CharField(max_length=20)
    branch = models.CharField(max_length=100)
    qr_code = models.ImageField(upload_to="payments/qr/", default="", storage=MediaCloudinaryStorage(), blank=True, null=True)

    def __str__(self):
        return f"Admin Account {self.account_number}"
    
class PasswordResetToken(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def __str__(self):
        return f"PasswordResetToken({self.user.user_id})"
    

class UserAccountDetails(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    account_number = models.CharField(max_length=30)
    ifsc = models.CharField(max_length=20)
    account_holder_name = models.CharField(max_length=100)
    branch = models.CharField(max_length=100)
    upi_number = models.CharField(max_length=50)   # auto-filled from registration
    upi_type = models.CharField(max_length=20, choices=PAYMENT_CHOICES)  # auto-filled from registration
    qr_code = models.ImageField(upload_to="user_qr_codes/", default="", storage=MediaCloudinaryStorage(), blank=True, null=True)

    def __str__(self):
        return f"AccountDetails({self.user.user_id})"

