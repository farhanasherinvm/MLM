from rest_framework import serializers
from .models import CustomUser

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'sponsor_name', 'placement_id', 'pincode', 'payment_type', 'upi_number',
            'first_name', 'last_name', 'email', 'mobile', 'whatsapp_number',
            'password', 'confirm_password', 'amount'
        ]

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Passwords do not match"})
        return data

    def validate_amount(self, value):
        if value < 100:
            raise serializers.ValidationError("Amount must be at least 100 rupees")
        return value

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        password = validated_data.pop('password')
        user = CustomUser.objects.create_user(
            password=password,
            **validated_data
        )
        return user
