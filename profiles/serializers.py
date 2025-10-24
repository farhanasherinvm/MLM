from rest_framework import serializers
from .models import Profile,KYC
from users.models import CustomUser, UserAccountDetails
from users.serializers import UserAccountDetailsSerializer
from datetime import date
from .utils import verhoeff_validate
from level.models import UserLevel
import re



def get_all_referrals(user_obj, max_level=6):
    """
    Returns a list of all referrals under a user up to `max_level` levels.
    """
    referrals = []
    level_users = [user_obj]  # start with current user
    current_level = 0

    while level_users and current_level < max_level:
        next_level_users = []
        for user in level_users:
            children = CustomUser.objects.filter(sponsor_id=user.user_id)
            next_level_users.extend(children)
            referrals.extend(children)
        level_users = next_level_users
        current_level += 1

    return referrals




class ReferralListSerializer(serializers.ModelSerializer):
    level = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    joined_date = serializers.DateTimeField(
        source="date_of_joining", format="%Y-%m-%d %H:%M:%S", read_only=True
    )
    direct_count = serializers.SerializerMethodField()
    total_count = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()

    # Extra fields
    position = serializers.SerializerMethodField()
    referred_by_id = serializers.SerializerMethodField()
    referred_by_name = serializers.SerializerMethodField()

    # Profile-related fields
    district = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    place = serializers.SerializerMethodField()
    pincode = serializers.SerializerMethodField()
    whatsapp_number = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "user_id", "first_name", "last_name", "email", "mobile",
            "level", "status", "joined_date",
            "direct_count", "total_count", "percentage",
            "position", "referred_by_id", "referred_by_name",
            "district", "state", "address", "place", "pincode",
            "whatsapp_number", "profile_image",
        ]

    # ----------------- Custom Getters -----------------
    def get_status(self, obj):
        return "Active" if obj.is_active else "Inactive"

    def get_direct_count(self, obj):
        return CustomUser.objects.filter(sponsor_id=obj.user_id).count()

    def get_total_count(self, obj):
        all_referrals = get_all_referrals(obj, max_level=6)
        return len(all_referrals)

    def get_percentage(self, obj):
        direct = self.get_direct_count(obj)
        percentage = (direct / 2) * 100  # goal = 2 direct referrals
        return f"{percentage:.0f}%"

    def get_position(self, obj):
        """Return Left or Right position under sponsor"""
        if obj.sponsor_id:
            siblings = list(CustomUser.objects.filter(sponsor_id=obj.sponsor_id).order_by("id")[:2])
            try:
                index = siblings.index(obj)
                return "Left" if index == 0 else "Right"
            except ValueError:
                return None
        return None

    def get_level(self, obj):
        """Return only level number (e.g., Level 1, Level 2)"""
        level_map = self.context.get("level_map", {})
        current_level = level_map.get(obj.user_id, 1)
        return f"Level {current_level}"

    def get_referred_by_id(self, obj):
        return obj.sponsor_id

    def get_referred_by_name(self, obj):
        if obj.sponsor_id:
            try:
                sponsor = CustomUser.objects.get(user_id=obj.sponsor_id)
                return f"{(sponsor.first_name or '').strip()} {(sponsor.last_name or '').strip()}"
            except CustomUser.DoesNotExist:
                return None
        return None

    # ----------------- Profile Fields -----------------
    def get_district(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.district if profile else None

    def get_state(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.state if profile else None

    def get_address(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.address if profile else None

    def get_place(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.place if profile else None

    def get_pincode(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.pincode if profile else None

    def get_whatsapp_number(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.whatsapp_number if profile else None

    def get_profile_image(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.profile_image:
            return profile.profile_image.url
        return None

class ProfileSerializer(serializers.ModelSerializer):
    # User fields
    user_id = serializers.CharField(source='user.user_id', read_only=True)
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    email = serializers.EmailField(source='user.email', read_only=True)
    mobile = serializers.CharField(source='user.mobile')
    date_of_join = serializers.DateTimeField(
        source="user.date_of_joining", format="%Y-%m-%d %H:%M:%S", read_only=True
    )

    # Dynamic fields
    placements = serializers.SerializerMethodField()     # tree users (placement-based)
    referrals = serializers.SerializerMethodField()      # sponsor-based users
    
    referred_by_id = serializers.SerializerMethodField()
    referred_by_name = serializers.SerializerMethodField()
    count_out_of_2 = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    placement_id = serializers.CharField(source='user.placement_id', read_only=True)

    # Profile fields
    district = serializers.CharField(required=False, allow_blank=True)
    state = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    place = serializers.CharField(required=False, allow_blank=True)
    pincode = serializers.CharField(required=False, allow_blank=True)
    whatsapp_number = serializers.CharField(required=False, allow_blank=True)
    profile_image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Profile
        fields = [
            "user_id", "first_name", "last_name", "email", "mobile",
            "status", "date_of_join", "count_out_of_2", "percentage",
            "referred_by_id", "referred_by_name", "placement_id",
            "district", "state", "address", "place", "pincode",
            "whatsapp_number", "profile_image",
             "placements", "referrals",
        ]

    # ---------- Update method ----------
    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        user = instance.user
        for attr, value in user_data.items():
            setattr(user, attr, value)
        user.save()

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    # ---------- Common helpers ----------
    def get_status(self, obj):
        return "Active" if obj.user.is_active else "Inactive"

    def get_referred_by_id(self, obj):
        return obj.user.sponsor_id or None

    def get_referred_by_name(self, obj):
        return self._get_sponsor_name(obj.user)

    def _get_sponsor_name(self, user):
        if user.sponsor_id:
            try:
                sponsor = CustomUser.objects.get(user_id__iexact=user.sponsor_id)
                return f"{(sponsor.first_name or '').strip()} {(sponsor.last_name or '').strip()}".strip()
            except CustomUser.DoesNotExist:
                return None
        return None

    def get_count_out_of_2(self, obj):
        placed_count = CustomUser.objects.filter(placement_id=obj.user.user_id).count()
        return f"{placed_count}/2"

    def get_percentage(self, obj):
        placed_count = CustomUser.objects.filter(placement_id=obj.user.user_id).count()
        return f"{(placed_count / 2) * 100:.0f}%"

   

    # ---------- Placements Tree (recursive) ----------
    def get_placements(self, obj):
        return self._build_levels(obj.user.user_id)

    def _build_levels(self, user_id, level=1, max_level=6):
        if level > max_level:
            return {}
        slots = [
            {"position": "Left", "status": "Not Available"},
            {"position": "Right", "status": "Not Available"},
        ]

        children = list(CustomUser.objects.filter(placement_id=user_id).order_by("id")[:2])
        for i, child in enumerate(children):
            profile = getattr(child, "profile", None)
            child_count = CustomUser.objects.filter(placement_id=child.user_id).count()
            slots[i] = {
                "position": "Left" if i == 0 else "Right",
                "user_id": child.user_id,
                "name": f"{child.first_name} {child.last_name}",
                "email": child.email,
                "mobile": child.mobile,
                "status": "Active" if child.is_active else "Inactive",
                "placement_id": child.placement_id,
                "placement_status": "Placed",
                "date_of_join": child.date_of_joining.strftime("%Y-%m-%d %H:%M:%S"),
                "count_out_of_2": f"{child_count}/2",
                "percentage": f"{(child_count / 2) * 100:.0f}%",
                "referred_by_id": child.sponsor_id,
                "referred_by_name": self._get_sponsor_name(child),
                "profile_image": profile.profile_image.url if profile and profile.profile_image else None,
                "next_level": self._build_levels(child.user_id, level + 1, max_level),
            }
        return {f"Level {level}": slots}

    # ---------- Referrals ----------
    def get_referrals(self, obj):
        """Show all sponsor-based users (referrals) and whether placed or pending"""
        referrals = CustomUser.objects.filter(sponsor_id=obj.user.user_id).select_related("profile").order_by("id")
        data = []
        for user in referrals:
            profile = getattr(user, "profile", None)
            data.append({
                "user_id": user.user_id,
                "name": f"{user.first_name} {user.last_name}".strip(),
                "email": user.email,
                "mobile": user.mobile,
                "placement_status": "Placed" if user.placement_id else "Pending Placement",
                "status": "Active" if user.is_active else "Inactive",
                "date_of_join": user.date_of_joining.strftime("%Y-%m-%d %H:%M:%S"),
                "district": profile.district if profile else None,
                "state": profile.state if profile else None,
                "place": profile.place if profile else None,
                "profile_image": profile.profile_image.url if profile and profile.profile_image else None,
            })
        return data


class KYCSerializer(serializers.ModelSerializer):
    # Map nominee fields
    id_number_nominee = serializers.CharField(source='id_number', allow_blank=False)
    id_card_image_nominee = serializers.ImageField(source='id_card_image')
    nominee_dob = serializers.DateField(required=False, allow_null=True)
    pan_number = serializers.CharField(required=True, allow_blank=False)
    class Meta:
        model = KYC
        fields = [
            "id",
            "aadhaar_number",
            "pan_number",
            "pan_image",
            "id_number_nominee",
            "id_card_image_nominee",
            "nominee_name",
            "nominee_relation",
            "nominee_dob",
            "verified",
            "created_at",
        ]
        read_only_fields = ["verified", "created_at"]

    def validate_nominee_dob(self, value):
        today = date.today()
        # Calculate the date 18 years ago
        required_age_date = today.replace(year=today.year - 18)

        # Check if the DOB is provided and if the nominee is under 18
        if value and value > required_age_date:
            raise serializers.ValidationError("Nominee must be at least 18 years old.")
        
        return value

    def validate_aadhaar_number(self, value):
        value = value.replace(" ", "")  # Remove spaces

        # Check 12-digit format
        if not re.fullmatch(r'\d{12}', value):
            raise serializers.ValidationError("Aadhaar number must be a 12-digit number.")

        # Verhoeff checksum
        if not verhoeff_validate(value):
            raise serializers.ValidationError("Invalid Aadhaar number (failed checksum).")

        # Check uniqueness
        user = self.context['request'].user
        if KYC.objects.exclude(user=user).filter(aadhaar_number=value).exists():
            raise serializers.ValidationError("This Aadhaar number is already used by another user.")

        return value

    def validate_id_number(self, value):
        user = self.context['request'].user
        # Check if ID number already exists for another user
        if KYC.objects.exclude(user=user).filter(id_number=value).exists():
            raise serializers.ValidationError("This ID number is already used by another user.")
        return value
    def validate_pan_number(self, value):
        if not value:
         raise serializers.ValidationError("PAN number cannot be empty.")
        user = self.context['request'].user
        if KYC.objects.exclude(user=user).filter(pan_number=value).exists():
           raise serializers.ValidationError("This PAN number is already used by another user.")
        return value

class ReferralSerializer(serializers.Serializer):
    referral_id = serializers.CharField()

#    Serializer for Admin user listing

class AdminUserListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for admin listing
    """
    username = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    date_of_joining = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ["username", "user_id", "level", "profile_image", "status", "date_of_joining"]

    def get_username(self, obj):
        first = getattr(obj, "first_name", "") or ""
        last = getattr(obj, "last_name", "") or ""
        full = f"{first} {last}".strip()
        return full if full else obj.user_id

    def get_profile_image(self, obj):
        try:
            profile = getattr(obj, "profile", None)
            if profile and profile.profile_image:
                return profile.profile_image.url
        except Exception:
            return None
        return None

    def get_level(self, obj):
        """
        Return the highest paid level for the user.
        """
        try:
            # Get all 'paid' levels for the user
            user_levels = UserLevel.objects.filter(user=obj, status='paid')
            
            if user_levels.exists():
                # Get the highest level (assuming 'level.order' is the order of the levels)
                highest_level = user_levels.order_by('-level__order').first()
                return highest_level.level.name  # Or return level.order if you prefer the order
            return ""
        except Exception as e:
            return ""  # Return an empty string if no level found or error occurs


    def get_status(self, obj):
        return "Active" if obj.is_active else "Blocked"

    def get_date_of_joining(self, obj):
        doj = getattr(obj, "date_of_joining", None)
        if doj:
            # format as YYYY-MM-DD
            return doj.strftime("%Y-%m-%d")
        return None
class AdminUserDetailSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)
    kyc = KYCSerializer(required=False)
    useraccountdetails = UserAccountDetailsSerializer(required=False)
    blocked_status = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "user_id", "first_name", "last_name", "email", "mobile",
            "whatsapp_number", "pincode", "payment_type", "upi_number",
            "sponsor_id", "placement_id",
            "is_active", "blocked_status", "level",
            "profile", "kyc", "useraccountdetails"
        ]
        # read_only_fields = ["user_id", "level"]

    def update(self, instance, validated_data):
        # --- Pop nested data ---
        profile_data = validated_data.pop("profile", {})
        kyc_data = validated_data.pop("kyc", {}) or {}
        account_data = validated_data.pop("useraccountdetails", {}) or {}

        # --- Update CustomUser fields ---
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # --- Update Profile (nested + flat form-data) ---
        profile, _ = Profile.objects.get_or_create(user=instance)
        for field in [
            "district", "state", "address", "place",
            "pincode", "whatsapp_number", "profile_image",
            "first_name", "last_name", "email", "mobile"
        ]:
            if field in self.context["request"].data:
                setattr(profile, field, self.context["request"].data.get(field))
            elif field in profile_data:
                setattr(profile, field, profile_data.get(field))
        profile.save()

        # --- Update KYC (including nominee fields) ---
        if kyc_data or any(f in self.context["request"].data for f in [
            "aadhaar_number", "pan_number", "pan_image",
            "id_number", "id_number_nominee", "id_card_image", "id_card_image_nominee",
            "nominee_name", "nominee_relation", "nominee_dob", "verified"
        ]):
            kyc, _ = KYC.objects.get_or_create(user=instance)
            for field_map in [
                ("aadhaar_number", "aadhaar_number"),
                ("pan_number", "pan_number"),
                ("pan_image", "pan_image"),
                ("id_number_nominee", "id_number"),
                ("id_card_image_nominee", "id_card_image"),
                ("nominee_name", "nominee_name"),
                ("nominee_relation", "nominee_relation"),
                ("nominee_dob", "nominee_dob"),
                ("verified", "verified"),
            ]:
                input_field, model_field = field_map
                # Priority 1: request.data
                if input_field in self.context["request"].data:
                    setattr(kyc, model_field, self.context["request"].data.get(input_field))
                # Priority 2: nested JSON
                elif input_field in kyc_data:
                    setattr(kyc, model_field, kyc_data.get(input_field))
                # Priority 3: fallback to direct model field names
                elif model_field in self.context["request"].data:
                    setattr(kyc, model_field, self.context["request"].data.get(model_field))
                elif model_field in kyc_data:
                    setattr(kyc, model_field, kyc_data.get(model_field))
            kyc.save()


        # --- Update UserAccountDetails (nested + flat form-data) ---
        if account_data or any(f in self.context["request"].data for f in [
            "account_number", "ifsc", "account_holder_name",
            "branch", "upi_number", "upi_type", "qr_code"
        ]):
            acc, _ = UserAccountDetails.objects.get_or_create(user=instance)
            for field in [
                "account_number", "ifsc", "account_holder_name",
                "branch", "upi_number", "upi_type", "qr_code"
            ]:
                # Update from request data first (supports multipart/form-data)
                if field in self.context["request"].data:
                    setattr(acc, field, self.context["request"].data.get(field))
                elif field in account_data:
                    setattr(acc, field, account_data.get(field))
            acc.save()

        return instance

    def get_profile_image(self, obj):
        if hasattr(obj, "profile") and obj.profile.profile_image:
            request = self.context.get("request")
            return (
                request.build_absolute_uri(obj.profile.profile_image.url)
                if request else obj.profile.profile_image.url
            )
        return None

    def get_blocked_status(self, obj):
        return "Unblocked" if obj.is_active else "Blocked"
    
    def get_level(self, obj):
        """
        Return the highest paid level for the user.
        """
        try:
            # Get all 'paid' levels for the user
            user_levels = UserLevel.objects.filter(user=obj, status='paid')
            
            if user_levels.exists():
                # Get the highest level (assuming 'level.order' is the order of the levels)
                highest_level = user_levels.order_by('-level__order').first()
                return highest_level.level.name  # Or return level.order if you prefer the order
            return ""
        except Exception as e:
            return ""  # Return an empty string if no level found or error occurs


    

class AdminNetworkUserSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    sponsor = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    joindate = serializers.DateTimeField(source="date_of_joining", format="%Y-%m-%d", read_only=True)
    profile_image = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "username",
            "sponsor",
            "level",
            "joindate",
            "status",
            "profile_image",
        ]

    def get_username(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.user_id

    def get_sponsor(self, obj):
        if obj.sponsor_id:
            try:
                sponsor = CustomUser.objects.get(user_id=obj.sponsor_id)
                sponsor_name = f"{sponsor.first_name} {sponsor.last_name}".strip()
                return f"{sponsor.user_id} / {sponsor_name}"
            except CustomUser.DoesNotExist:
                return "N/A"
        return "N/A"

    def get_status(self, obj):
        return "Active" if obj.is_active else "Blocked"

    def get_profile_image(self, obj):
        if hasattr(obj, "profile") and obj.profile and obj.profile.profile_image:
            request = self.context.get("request")
            return request.build_absolute_uri(obj.profile.profile_image.url) if request else obj.profile.profile_image.url
        return None

    def get_level(self, obj):
        """
        Return the highest paid level for the user.
        """
        try:
            # Get all 'paid' levels for the user
            user_levels = UserLevel.objects.filter(user=obj, status='paid')
            
            if user_levels.exists():
                # Get the highest level (assuming 'level.order' is the order of the levels)
                highest_level = user_levels.order_by('-level__order').first()
                return highest_level.level.name  # Or return level.order if you prefer the order
            return ""
        except Exception as e:
            return ""  # Return an empty string if no level found or error occurs


class CurrentUserProfileSerializer(serializers.ModelSerializer):
    # User fields
    user_id = serializers.CharField(source='user.user_id', read_only=True)
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    email = serializers.EmailField(source='user.email', read_only=True)
    mobile = serializers.CharField(source='user.mobile')
    date_of_join = serializers.DateTimeField(
        source='user.date_of_joining', format='%Y-%m-%d %H:%M:%S', read_only=True
    )

    class Meta:
        model = Profile
        fields = [
            'user_id', 'first_name', 'last_name', 'email', 'mobile',
            'date_of_join',
            'district', 'state', 'address', 'place', 'pincode',
            'whatsapp_number', 'profile_image',
        ]
