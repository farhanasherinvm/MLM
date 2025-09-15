from .models import CustomUser

def validate_sponsor(sponsor_id):
    try:
        sponsor = CustomUser.objects.get(user_id=sponsor_id)
        referrals_count = CustomUser.objects.filter(sponsor_id=sponsor_id).count()
        if referrals_count >= 2:
            return False
        return True
    except CustomUser.DoesNotExist:
        return False
