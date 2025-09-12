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
        read_only_fields = ["first_name", "last_name", "email", "pincode", "mobile", "whatsapp_number"]
     
    def get_referrals(self, obj):
        user = obj.user  

        def fetch_referrals(user, level=1, max_level=6):
            if level > max_level:
                return []
            
            referrals = CustomUser.objects.filter(referred_by=user)
            data = []
            for u in referrals:
                data.append({
                    "level": level,
                    "user_id": u.user_id,
                    "name": f"{u.first_name} {u.last_name}",
                    "email": u.email,
                    "mobile": u.mobile,
                    "referrals": fetch_referrals(u, level + 1, max_level)  # recursion
                })
            return data

        return fetch_referrals(user)
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