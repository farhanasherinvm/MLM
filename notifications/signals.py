from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from notifications.models import Notification
from level.models import UserLevel  
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

@receiver(post_save, sender=User)
def create_user_notification(sender, instance, created, **kwargs):
    if created:
        try:
            Notification.objects.create(
                user=instance,
                message=f"Welcome {instance.first_name}! Your account has been created."
            )
            logger.debug(f"Created notification for user {instance.first_name} creation")
        except Exception as e:
            logger.error(f"Failed to create notification for user {instance.first_name}: {str(e)}")

@receiver(post_save, sender=UserLevel)
def create_payment_notification(sender, instance, created, **kwargs):
    if not created and instance.status == 'paid':
        try:
            Notification.objects.create(
                user=instance.user,
                message=f"Payment of {instance.level.amount} for {instance.level.name} has been successfully completed."
            )
            logger.debug(f"Created notification for payment completion: {instance.user.first_name} - {instance.level.name}")
        except Exception as e:
            logger.error(f"Failed to create notification for payment {instance.user.first_name} - {instance.level.name}: {str(e)}")