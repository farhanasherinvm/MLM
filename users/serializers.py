from django.contrib.auth.hashers import make_password
from rest_framework import serializers
from .models import *
from django.contrib.auth import get_user_model
from .utils import validate_sponsor

User = get_user_model()

class SendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField()
    
class RegistrationSerializer(serializers.Serializer):
    sponsor_id = serializers.CharField(required=False, allow_blank=True)
    placement_id = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    mobile = serializers.CharField()
    whatsapp_number = serializers.CharField()
    pincode = serializers.CharField()
    payment_type = serializers.ChoiceField(choices=CustomUser.PAYMENT_CHOICES)
    upi_number = serializers.CharField()
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=100)


    def validate(self, data):
    # Check password match
        if data["password"] != data["confirm_password"]:
         raise serializers.ValidationError({"password": "Passwords do not match."})

    # Check sponsor exists
        sponsor_id = data.get("sponsor_id")
        if sponsor_id and not validate_sponsor(sponsor_id):
            raise serializers.ValidationError({"sponsor_id": "Sponsor ID does not exist."})

    # Check placement ID validity and limit
        placement_id = data.get("placement_id")
        if placement_id:  # Only validate if provided
            placement_user = CustomUser.objects.filter(user_id=placement_id).first()
            if not placement_user:
             raise serializers.ValidationError({"placement_id": f"No user with ID {placement_id} exists in the system."})

        # Count users already placed under this placement_id
            placed_count = CustomUser.objects.filter(placement_id=placement_id).count()
            if placed_count >= 2:
             raise serializers.ValidationError({
                 "placement_id": "Placement limit reached for this user. Please choose another placement or leave it empty."
             })

        return data

    # def create_payment(self, validated_data):
    #     data_copy = dict(validated_data)
    #     password = data_copy.pop("password")
    #     data_copy.pop("confirm_password", None)   # ✅ don’t store confirm_password
    #     if not password:
    #         raise serializers.ValidationError({"password": "Password is required."})
    #     data_copy["password"] = password
    #     payment = Payment.objects.create()
    #     payment.set_registration_data(data_copy)
    #     return payment
    
class RazorpayOrderSerializer(serializers.Serializer):
    registration_token = serializers.UUIDField()

class RazorpayVerifySerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(required=True)
    razorpay_payment_id = serializers.CharField(required=True)
    razorpay_signature = serializers.CharField(required=True)

class UploadReceiptSerializer(serializers.ModelSerializer):
    registration_token = serializers.UUIDField(write_only=True)
    receipt = serializers.FileField(required=True)  # ✅ ensure it must be sent

    class Meta:
        model = Payment
        fields = ["registration_token", "receipt"]

    def create(self, validated_data):
        registration_token = validated_data.pop("registration_token")
        try:
            payment = Payment.objects.get(registration_token=registration_token, status="Pending")
        except Payment.DoesNotExist:
            raise serializers.ValidationError({"error": "Invalid or expired registration token."})

        payment.receipt = validated_data.get("receipt")  # safer
        payment.save()
        return payment

    
class AdminAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminAccountDetails
        fields = "__all__"

class LoginSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user_id = data.get("user_id")
        password = data.get("password")

        try:
            user = CustomUser.objects.get(user_id=user_id)
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError("Invalid UserID or password.")
        
         # For child login: password is mandatory
        if user.role == "child" and not password:
            raise serializers.ValidationError("Child must provide a password to login.")


        if not user.check_password(password):
            raise serializers.ValidationError("Invalid UserID or password.")

        # ✅ Only allow login if payment/registration verified
        if not user.is_active and not user.is_superuser:
            raise serializers.ValidationError("This account is not active. Complete payment verification.")

        data["user"] = user
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    email = serializers.EmailField()

    def validate(self, data):
        try:
            user = User.objects.get(user_id=data['user_id'], email=data['email'])
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid User ID or Email.")
        data['user'] = user
        return data
    
class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField(required=False)  # can be query param
    new_password = serializers.CharField()
    confirm_password = serializers.CharField()

    def validate(self, data):
        token = data.get('token') or self.context.get('token')
        if not token:
            raise serializers.ValidationError("Token is required.")

        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords do not match.")
        
        try:
            reset_token = PasswordResetToken.objects.get(token=token, is_used=False)
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError("Invalid or expired token.")
        data['reset_token'] = reset_token
        return data
    
class UserAccountDetailsSerializer(serializers.ModelSerializer):
    confirm_account_number = serializers.CharField(write_only=True)

    class Meta:
        model = UserAccountDetails
        fields = [
            "account_number",
            "confirm_account_number",
            "ifsc",
            "account_holder_name",
            "branch",
            "upi_number",
            "upi_type",
            "qr_code",
        ]

    def validate(self, data):
        if data.get("account_number") != data.get("confirm_account_number"):
            raise serializers.ValidationError("Account number and confirm account number must match.")
        return data

    def create(self, validated_data):
        validated_data.pop("confirm_account_number", None)
        return UserAccountDetails.objects.create(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("confirm_account_number", None)
        return super().update(instance, validated_data)


class CustomUserSerializer(serializers.ModelSerializer):

    level = serializers.IntegerField(source="level", read_only=True)
    class Meta:
        model = CustomUser
        fields = [
            "user_id",
            "first_name",
            "last_name",
            "email",
            "mobile",
            "whatsapp_number",
            "payment_type",
            "upi_number",
            "is_active",
            "sponsor_id",
            "placement_id",
            'level',
        ]


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    level = serializers.IntegerField(source="level", read_only=True)
    profile_image = serializers.ImageField(source="profile.profile_image", required=False)
    district = serializers.CharField(source="profile.district", required=False, allow_blank=True)
    state = serializers.CharField(source="profile.state", required=False, allow_blank=True)
    address = serializers.CharField(source="profile.address", required=False, allow_blank=True)
    place = serializers.CharField(source="profile.place", required=False, allow_blank=True)
    pincode = serializers.CharField(source="profile.pincode", required=False)

    class Meta:
        model = CustomUser
        fields = [
            "first_name", "last_name", "email", "mobile", "whatsapp_number",
            "sponsor_id", "placement_id", "is_active", "level",
            "profile_image", "district", "state", "address", "place", "pincode"
        ]

    def update(self, instance, validated_data):
        # ✅ Extract nested profile data
        profile_data = validated_data.pop("profile", {})

        # ✅ Update CustomUser fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # ✅ Update Profile fields if they exist
        profile = getattr(instance, "profile", None)
        if profile and profile_data:
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()

        return instance

class AdminEditUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "email",
            "mobile",
            "whatsapp_number",
            "pincode",
            "payment_type",
            "upi_number",
            "password",
            "level",
        ]
        extra_kwargs = {
            "email": {"required": False},
            "mobile": {"required": False},
        }

    def update(self, instance, validated_data):
        # If password is provided, hash it
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
    
class AdminUserListSerializer(serializers.ModelSerializer):
    sponsor = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    joindate = serializers.DateTimeField(source="date_of_joining", format="%Y-%m-%d", read_only=True)
    username = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ["username", "sponsor", "level", "joindate", "status", "profile_image"]

    def get_username(self, obj):
        """Combine first and last name."""
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_sponsor(self, obj):
        """Return sponsor as 'user_id / Full Name' or 'null'."""
        if obj.sponsor_id:
            try:
                sponsor = CustomUser.objects.get(user_id=obj.sponsor_id)
                sponsor_name = f"{sponsor.first_name} {sponsor.last_name}".strip()
                return f"{sponsor.user_id} / {sponsor_name}"
            except CustomUser.DoesNotExist:
                return "null"
        return "null"

    def get_status(self, obj):
        return "Active" if obj.is_active else "Blocked"
    
    extra_debug = serializers.SerializerMethodField()

    def get_extra_debug(self, obj):
        return "✅ Using AdminUserListSerializer"


    def get_profile_image(self, obj):
        """Return absolute URL for profile image if available."""
        if hasattr(obj, "profile") and obj.profile and obj.profile.profile_image:
            request = self.context.get("request")
            return request.build_absolute_uri(obj.profile.profile_image.url)
        return None

class UserFullNameSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    full_name = serializers.CharField()



class ChildRegistrationSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    mobile = serializers.CharField(required=False, allow_blank=True)
    whatsapp_number = serializers.CharField(required=False, allow_blank=True)
    pincode = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)  # mandatory for child

    def create(self, validated_data):
        parent = self.context['request'].user
        password = validated_data.pop('password')

        # Create child user
        child_user = CustomUser.objects.create(
            parent=parent,
            sponsor_id=parent.user_id,
            placement_id=None,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            email=validated_data.get('email', ''),
            mobile=validated_data.get('mobile', ''),
            whatsapp_number=validated_data.get('whatsapp_number', ''),
            pincode=validated_data.get('pincode', ''),
            payment_type='Other',  # child doesn’t pay
            upi_number='',
            is_active=True,
            pmf_status=False,
        )

        # Child must have password for individual login
        child_user.set_password(password)
        child_user.save()
        return child_user
