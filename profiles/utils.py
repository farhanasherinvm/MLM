
from django.contrib.auth import get_user_model
CustomUser = get_user_model()

def get_all_referrals(user, max_level=6):
    result = []

    def fetch(u, level):
        if level > max_level:
            return

        children = list(CustomUser.objects.filter(sponsor_id=u.user_id).order_by("id"))

        for idx, child in enumerate(children):
            # Mark placement vs referral
            if idx < 2:
                child.temp_type = "Placement"   # First 2 users are placements
                child.temp_position = "Left" if idx == 0 else "Right"
            else:
                child.temp_type = "Referral"    # Others are referrals
                child.temp_position = None

            child.temp_level = level
            result.append(child)

            fetch(child, level + 1)

    fetch(user, 1)
    return result
