from rest_framework import serializers
from .models import Profile,KYC
from users.models import CustomUser


class ProfileSerializer(serializers.ModelSerializer):
    referrals = serializers.SerializerMethodField()
    referred_by_id = serializers.SerializerMethodField()
    referred_by_name = serializers.SerializerMethodField()
    count_out_of_2 = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    date_of_join = serializers.DateTimeField(source="user.created_at", format="%Y-%m-%d %H:%M:%S")

    class Meta:
        model = Profile
        fields = [
            "user_id", "first_name", "last_name", "email", "mobile",
            "status", "date_of_join", "count_out_of_2", "percentage",
            "referred_by_id", "referred_by_name", "referrals",
        ]

    def get_user_id(self, obj):
        return obj.user.user_id

    def get_status(self, obj):
        return "Active" if obj.user.is_active else "Inactive"

    def get_referred_by_id(self, obj):
        return obj.user.referred_by.user_id if obj.user.referred_by else None

    def get_referred_by_name(self, obj):
        return f"{obj.user.referred_by.first_name} {obj.user.referred_by.last_name}" if obj.user.referred_by else None

    def get_count_out_of_2(self, obj):
        return f"{obj.user.referrals.count()}/2"

    def get_percentage(self, obj):
        return f"{(obj.user.referrals.count() / 2) * 100:.0f}%"

    def get_referrals(self, obj):
        user = obj.user  

        def build_levels(user, level=1, max_level=6):
            if level > max_level:
                return {}

            slots = [
                {"position": "Left", "status": "Not Available"},
                {"position": "Right", "status": "Not Available"},
            ]

            referrals = list(CustomUser.objects.filter(referred_by=user)[:2])

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


class ReferralListSerializer(serializers.ModelSerializer):
    level = serializers.IntegerField()
    status = serializers.SerializerMethodField()
    joined_date = serializers.DateTimeField(source="created_at", read_only=True)
    count = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "user_id", "first_name", "last_name", "email", "mobile",
            "level", "status", "joined_date", "count", "percentage"
        ]

    def get_status(self, obj):
        return "Active" if obj.is_active else "Inactive"

    def get_count(self, obj):
        return f"{obj.referrals.count()}/2"

    def get_percentage(self, obj):
        return f"{(obj.referrals.count() / 2) * 100}%"