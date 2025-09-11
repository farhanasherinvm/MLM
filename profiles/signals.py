from django.db.models.signals import post_save
from django.dispatch import receiver
from users.models import CustomUser
from .models import Profile

@receiver(post_save, sender=CustomUser)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(
            user=instance,
            first_name=instance.first_name,
            last_name=instance.last_name,
            email=instance.email,
            pincode=instance.pincode,
            mobile=instance.mobile,
            whatsapp_number=instance.whatsapp_number
        )
