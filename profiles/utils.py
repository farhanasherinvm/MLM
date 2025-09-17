from django.contrib.auth import get_user_model
CustomUser = get_user_model()

def get_all_referrals(user, max_level=6):
    result = []

    def fetch(u, level):
        if level > max_level:
            return
        
        # Change `referred_by` to `sponsor_id`
        referrals = CustomUser.objects.filter(sponsor_id=u)
        
        for r in referrals:
            r.level = level   # attach level temporarily
            result.append(r)
            fetch(r, level + 1)

    fetch(user, 1)
    return result