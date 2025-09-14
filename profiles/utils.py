from django.contrib.auth import get_user_model
CustomUser = get_user_model()

def get_all_referrals(user, max_level=6):
    result = []

    def fetch(u, level):
        if level > max_level:
            return
        referrals = CustomUser.objects.filter(referred_by=u)
        for r in referrals:
            r.level = level   # attach level temporarily
            result.append(r)
            fetch(r, level + 1)

    fetch(user, 1)
    return result
