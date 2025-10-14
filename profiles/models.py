from django.db import models
from django.conf import settings
from cloudinary_storage.storage import MediaCloudinaryStorage
def upload_to_kyc(instance, filename):
    return f"kyc/{instance.user.id}/{filename}"


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    
    # Additional profile fields
    district = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    place = models.CharField(max_length=100, blank=True, null=True)
    profile_image = models.ImageField(upload_to='profile_images/', default="", storage=MediaCloudinaryStorage(), blank=True, null=True)

    # Fetchable fields from user for convenience
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    pincode = models.CharField(max_length=10)
    mobile = models.CharField(max_length=15)
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True)

    def __str__(self):
        return f"{self.user.user_id} Profile"


class KYC(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kyc"
    )

    #  aadhaar number
    aadhaar_number = models.CharField(max_length=12, unique=True, null=True, blank=True)


    # PAN details
    pan_number = models.CharField(max_length=20, unique=True, blank=False, null=False)
    pan_image = models.ImageField(upload_to=upload_to_kyc, default="", storage=MediaCloudinaryStorage(), null=True, blank=True)

    # ID details
    id_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    id_card_image = models.ImageField(upload_to=upload_to_kyc, default="", storage=MediaCloudinaryStorage(), null=True, blank=True)

    # Nominee details
    nominee_name = models.CharField(max_length=100)
    nominee_relation = models.CharField(max_length=50)
    nominee_dob = models.DateField(null=True, blank=True)

    verified = models.BooleanField(default=False)  # Admin can update this
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"KYC - {self.user.email}"

