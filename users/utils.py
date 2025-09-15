from users.models import CustomUser

def validate_sponsor(sponsor_id: str) -> bool:
    """
    Validate sponsor:
      1. Sponsor must exist in the system.
      2. Sponsor must have less than 2 referrals.
    """
    try:
        sponsor = CustomUser.objects.get(user_id=sponsor_id)
    except CustomUser.DoesNotExist:
        return False

    # Count referrals (users who have this sponsor_id)
    referral_count = CustomUser.objects.filter(sponsor_id=sponsor_id).count()
    if referral_count >= 2:
        return False

    return True
