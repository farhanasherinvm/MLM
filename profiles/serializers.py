from rest_framework import serializers
from .models import Profile,KYC

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            "first_name", "last_name", "email", "pincode", "mobile", "whatsapp_number",
            "district", "state", "address", "place", "profile_image"
        ]
        read_only_fields = ["first_name", "last_name", "email", "pincode", "mobile", "whatsapp_number"]

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