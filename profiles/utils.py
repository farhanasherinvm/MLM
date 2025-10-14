
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


# Multiplication table
verhoeff_d = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,2,3,4,0,6,7,8,9,5],
    [2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8],
    [5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],
    [7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0]
]

# Permutation table
verhoeff_p = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,5,7,6,2,8,3,0,9,4],
    [5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],
    [9,4,5,3,1,2,6,8,7,0],
    [4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],
    [7,0,4,6,9,1,3,2,5,8]
]

# Inverse table
verhoeff_inv = [0,4,3,2,1,5,6,7,8,9]

def verhoeff_validate(number):
    """Check if number passes Verhoeff checksum."""
    number = number[::-1]  # Reverse digits
    c = 0
    for i, digit in enumerate(number):
        c = verhoeff_d[c][verhoeff_p[i % 8][int(digit)]]
    return c == 0
