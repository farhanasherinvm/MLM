from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F 
from level import constants 
from .models import UserLevel, LevelPayment 
from users.models import CustomUser 
import logging
from users.utils import get_rebirth_cap_status
logger = logging.getLogger(__name__)


def check_and_enforce_payment_lock(receiving_user, level_amount_to_credit):

    if receiving_user.user_id.startswith('MASTER'):
        return True, "Payment allowed: Receiving user is the Master Node."
    
    FEE_LEVEL_NAMES = [
        constants.LOCK_LEVEL_NAME, 
        constants.PMF_PART_1_NAME, 
        constants.PMF_PART_2_NAME
    ]
    # 1. Calculate total received (Always required to check the cap)
    aggregation_result = UserLevel.objects.filter(user=receiving_user)\
        .exclude(level__name__in=FEE_LEVEL_NAMES)\
        .aggregate(total_received=Sum('received'))

    total_received = aggregation_result['total_received'] or Decimal('0.00')

    can_receive, value_or_msg, *child_info = get_rebirth_cap_status(receiving_user, total_received)
    
    if not can_receive:
        # This is where the payment is restricted
        cap_amount = value_or_msg
        next_child_number = child_info[0] 
        
        return False, (
            f"Payment restricted: R{cap_amount} Rebirth/Child Cap reached. "
            f"Please create Child #{next_child_number} to unlock this payment."
        )

    # -----------------------------------------------------------------
    # 2. CHECK CAP 2 (R30,000) - NEW PMF Part 2 Lock
    # -----------------------------------------------------------------
    if total_received >= constants.CAP_2_AMOUNT:
        if receiving_user.pmf_status != constants.PMF_STATUS_PAID:
            return False, (
                f"Payment restricted: R{constants.CAP_2_AMOUNT} cap reached. "
                f"Please pay **{constants.PMF_PART_2_NAME} (R{constants.PMF_PART_2_AMOUNT})** to unlock."
            )

    # -----------------------------------------------------------------
    # 3. CHECK CAP 1 (R15,000) - NEW PMF Part 1 Lock
    # -----------------------------------------------------------------
    elif total_received >= constants.CAP_1_AMOUNT:
        if receiving_user.pmf_status == constants.PMF_STATUS_NOT_PAID:
            return False, (
                f"Payment restricted: R{constants.CAP_1_AMOUNT} cap reached. "
                f"Please pay **{constants.PMF_PART_1_NAME} (R{constants.PMF_PART_1_AMOUNT})** to unlock."
            )

    # -----------------------------------------------------------------
    # 4. CHECK REFER HELP CAP (R4,700) - EXISTING LOGIC
    # -----------------------------------------------------------------
    elif total_received >= constants.PAYMENT_CAP_AMOUNT:
        
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