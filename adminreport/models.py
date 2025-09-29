from django.db import models
from django.utils import timezone
from users.models import CustomUser
from level.models import UserLevel, LevelPayment
from django.db.models.signals import post_save
from django.dispatch import receiver

class AdminNotification(models.Model):
    OPERATION_CHOICES = [
        ('level_payment', 'Level Payment'),
        ('status_update', 'Status Update'),
        ('linked_user_change', 'Linked User Change'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    operation_type = models.CharField(max_length=20, choices=OPERATION_CHOICES)
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gic = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # 18% of amount
    user_level = models.ForeignKey(UserLevel, on_delete=models.CASCADE, null=True, blank=True)
    level_payment = models.ForeignKey(LevelPayment, on_delete=models.CASCADE, null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.operation_type} - {self.user.user_id} at {self.timestamp}"

    def save(self, *args, **kwargs):
        if self.amount and self.gic is None:
            self.gic = self.amount * 0.18
        super().save(*args, **kwargs)

@receiver(post_save, sender=LevelPayment)
def log_payment_notification(sender, instance, created, **kwargs):
    if created or (not created and instance.status in ['Verified', 'Paid']):
        user_level = instance.user_level
        user = user_level.user
        amount = instance.amount
        description = f"User {user.user_id} paid Level {user_level.level.name} - Amount: ${amount}, GIC: ${amount * 0.18}, Status: {instance.status}"
        AdminNotification.objects.update_or_create(
            user=user,
            operation_type='level_payment',
            user_level=user_level,
            level_payment=instance,
            defaults={'description': description, 'amount': amount}
        )