from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F 
from level import constants 
from .models import UserLevel, LevelPayment 
from users.models import CustomUser 
import logging

logger = logging.getLogger(__name__)


def check_and_enforce_payment_lock(receiving_user, level_amount_to_credit):
    
    # 1. Calculate total received (Always required to check the cap)
    aggregation_result = UserLevel.objects.filter(user=receiving_user)\
        .exclude(level__name=constants.LOCK_LEVEL_NAME)\
        .aggregate(total_received=Sum('received'))

    total_received = aggregation_result['total_received'] or Decimal('0.00')

    # 2. Only proceed with lock logic if the cap is reached
    if total_received >= constants.PAYMENT_CAP_AMOUNT:
        
        # Cap is reached. Now we MUST check the lock level status.
        try:
            refer_help_level = UserLevel.objects.get(
                user=receiving_user, 
                level__name=constants.LOCK_LEVEL_NAME 
            )
        except UserLevel.DoesNotExist:
            # If the user hit the cap but the lock level is missing (Setup error),
            # we assume they are locked and return a clean restriction error.
            return False, (
                 f"Payment restricted: R{total_received} cap reached. "
                 f"Lock level '{constants.LOCK_LEVEL_NAME}' is missing. Please contact support."
             )
        
        if refer_help_level.status != 'paid':
            return False, (
                f"Payment restricted: R{total_received} cap reached. "
                f"Please pay the '{constants.LOCK_LEVEL_NAME}' level to unlock."
            )
        
        
        return True, "Payment unlocked via Refer Help."

    # 3. Cap not reached. Payment is allowed.
    return True, "Payment allowed: Cap not yet reached."


def credit_level_payment(level_payment_instance: LevelPayment):
    
    payment_amount = level_payment_instance.amount
    referrer_user_id = level_payment_instance.user_level.linked_user_id

    if not referrer_user_id:
        level_payment_instance.status = constants.CREDITED_STATUS
        level_payment_instance.save()
        return True, "Payment completed, no referrer credit required."

    try:
        referrer = CustomUser.objects.get(user_id=referrer_user_id)
    except CustomUser.DoesNotExist:
        return False, f"Setup Error: Referrer (user_id: {referrer_user_id}) not found."

    level_being_paid = level_payment_instance.user_level.level
    
    try:
        referrer_user_level = UserLevel.objects.get(
            user=referrer,
            level=level_being_paid
        )
    except UserLevel.DoesNotExist:
        return False, f"Setup Error: Referrer does not hold UserLevel for {level_being_paid.name}."
    
    with transaction.atomic():
        UserLevel.objects.filter(pk=referrer_user_level.pk).update(
            received=F('received') + payment_amount,
            balance=F('balance') + payment_amount
        )
        
        level_payment_instance.status = constants.CREDITED_STATUS 
        level_payment_instance.save()
    
    return True, "Payment credited."