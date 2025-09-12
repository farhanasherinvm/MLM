from rest_framework import serializers
from .models import CustomUser

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    referral_code = serializers.CharField(required=False, write_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'sponsor_name', 'placement_id', 'pincode', 'payment_type', 'upi_number',
            'first_name', 'last_name', 'email', 'mobile', 'whatsapp_number',
            'password', 'confirm_password', 'amount', 'referral_code'
        ]

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Passwords do not match"})

        referral_code = data.get('referral_code')
        if referral_code:
            try:
                referrer = CustomUser.objects.get(user_id=referral_code)
                if referrer.referrals.count() >= 2:
                    raise serializers.ValidationError(
                        {"referral_code": "This sponsor already referred 2 users."}
                    )
            except CustomUser.DoesNotExist:
                raise serializers.ValidationError({"referral_code": "Invalid referral code."})

        return data

    def validate_amount(self, value):
        if value < 100:
            raise serializers.ValidationError("Amount must be at least 100 rupees")
        return value

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        password = validated_data.pop('password')
        referral_code = validated_data.pop('referral_code', None)

        referrer = None
        if referral_code:
            referrer = CustomUser.objects.get(user_id=referral_code)

        user = CustomUser.objects.create_user(
            password=password,
            referred_by=referrer,
            **validated_data
        )

        return user
