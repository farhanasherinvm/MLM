from rest_framework import serializers
from .models import Profile,KYC
from users.models import CustomUser


class ProfileSerializer(serializers.ModelSerializer):
    referrals = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "first_name", "last_name", "email", "pincode", "mobile", "whatsapp_number",
            "district", "state", "address", "place", "profile_image", "referrals",
        ]
        read_only_fields = [
            "first_name", "last_name", "email", "pincode", "mobile", "whatsapp_number"
        ]

    def get_referrals(self, obj):
        user = obj.user  

        def build_levels(user, level=1, max_level=6):
            if level > max_level:
                return {}

            # Always 2 slots
            slots = [
                {"position": "Left", "status": "Not Available"},
                {"position": "Right", "status": "Not Available"},
            ]

            referrals = list(CustomUser.objects.filter(referred_by=user)[:2])  # max 2 children

            for i, child in enumerate(referrals):
                slots[i] = {
                    "position": "Left" if i == 0 else "Right",
                    "user_id": child.user_id,
                    "name": f"{child.first_name} {child.last_name}",
                    "email": child.email,
                    "mobile": child.mobile,
                    "status": "Active" if child.is_active else "Inactive",
                    "date_of_join": child.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "count_out_of_2": f"{child.referrals.count()}/2",
                    "percentage": f"{(child.referrals.count() / 2) * 100:.0f}%",
                    "referred_by_id": child.referred_by.user_id if child.referred_by else None,
                    "referred_by_name": f"{child.referred_by.first_name} {child.referred_by.last_name}" if child.referred_by else None,
                    "next_level": build_levels(child, level + 1, max_level),
                }

            return {f"Level {level}": slots}

        return build_levels(user)

class KYCSerializer(serializers.ModelSerializer):

    id_number_nominee = serializers.CharField(source='id_number')
    id_card_image_nominee = serializers.ImageField(source='id_card_image')
    class Meta:
        model = KYC
        fields = [
            "id",
            "account_number",
            "pan_number",
            "pan_image",
            "id_number_nominee",
            "id_card_image_nominee",
            "nominee_name",
            "nominee_relation",
            "verified",
            "created_at",
        ]
        read_only_fields = ["verified", "created_at"]

class ReferralSerializer(serializers.Serializer):
    referral_url = serializers.CharField(read_only=True)