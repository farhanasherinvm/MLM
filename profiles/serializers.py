from rest_framework import serializers
from .models import Profile,KYC
from users.models import CustomUser, UserAccountDetails
from users.serializers import UserAccountDetailsSerializer

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

    # Referral info
    referrals = serializers.SerializerMethodField()
    referred_by_id = serializers.SerializerMethodField()
    referred_by_name = serializers.SerializerMethodField()
    count_out_of_2 = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    # Profile fields (all writable)
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
            "referred_by_id", "referred_by_name",
            "district", "state", "address", "place", "pincode",
            "whatsapp_number", "profile_image",
            "referrals",
        ]

    # ---------- Update method ----------
    def update(self, instance, validated_data):
        # Update user fields
        user_data = validated_data.pop('user', {})
        user = instance.user
        for attr, value in user_data.items():
            setattr(user, attr, value)
        user.save()

        # Update profile fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    # ---------- SerializerMethodField methods ----------
    def get_status(self, obj):
        return "Active" if obj.user.is_active else "Inactive"

    def get_referred_by_id(self, obj):
        return obj.user.sponsor_id if obj.user.sponsor_id else None

    def get_referred_by_name(self, obj):
        return self.get_referred_by_name_for(obj.user)

    def get_referred_by_name_for(self, user):
        if user.sponsor_id:
            try:
                sponsor = CustomUser.objects.get(user_id__iexact=user.sponsor_id)
                return f"{(sponsor.first_name or '').strip()} {(sponsor.last_name or '').strip()}"
            except CustomUser.DoesNotExist:
                return None
        return None

    def get_count_out_of_2(self, obj):
        referred_count = CustomUser.objects.filter(sponsor_id=obj.user.user_id).count()
        return f"{referred_count}/2"

    def get_percentage(self, obj):
        referred_count = CustomUser.objects.filter(sponsor_id=obj.user.user_id).count()
        return f"{(referred_count / 2) * 100:.0f}%"

    def get_profile_image(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.profile_image:
            return profile.profile_image.url
        return None

    def get_referrals(self, obj):
        return self.build_levels(obj.user.user_id)

    # ---------- Recursive referral tree ----------
    def build_levels(self, user_id, level=1, max_level=6):
        if level > max_level:
            return {}

        slots = [
            {"position": "Left", "status": "Not Available"},
            {"position": "Right", "status": "Not Available"},
        ]

        referrals = list(CustomUser.objects.filter(sponsor_id=user_id)[:2])

        for i, child in enumerate(referrals):
            profile = getattr(child, "profile", None)
            slots[i] = {
                "position": "Left" if i == 0 else "Right",
                "user_id": child.user_id,
                "name": f"{child.first_name} {child.last_name}",
                "email": child.email,
                "mobile": child.mobile,
                "district": profile.district if profile else None,
                "state": profile.state if profile else None,
                "address": profile.address if profile else None,
                "place": profile.place if profile else None,
                "pincode": profile.pincode if profile else None,
                "whatsapp_number": profile.whatsapp_number if profile else None,
                "profile_image": profile.profile_image.url if profile and profile.profile_image else None,
                "status": "Active" if child.is_active else "Inactive",
                "date_of_join": child.date_of_joining.strftime("%Y-%m-%d %H:%M:%S"),
                "count_out_of_2": f"{CustomUser.objects.filter(sponsor_id=child.user_id).count()}/2",
                "percentage": f"{(CustomUser.objects.filter(sponsor_id=child.user_id).count() / 2) * 100:.0f}%",
                "referred_by_id": child.sponsor_id,
                "referred_by_name": self.get_referred_by_name_for(child),
                "next_level": self.build_levels(child.user_id, level + 1, max_level),
            }

        return {f"Level {level}": slots}


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
    referral_id = serializers.CharField()

#    Serializer for Admin user listing

class AdminUserListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for admin listing
    """
    username = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    status= serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ["username", "user_id", "level", "profile_image", "status"]

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
        try:
            level = 0
            visited = set()
            current = obj
            while getattr(current, "referred_by", None):
                rid = getattr(current.referred_by, "user_id", None)
                if not rid or rid in visited:
                    break
                visited.add(rid)
                level += 1
                current = current.referred_by
            return level
        except Exception:
            return 0
        
    def get_status(self, obj):
        return "Active" if obj.is_active else "Blocked"


class AdminUserDetailSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)
    kyc = KYCSerializer(required=False)
    useraccountdetails = UserAccountDetailsSerializer(required=False)
    blocked_status = serializers.SerializerMethodField()


    class Meta:
        model = CustomUser
        fields = [
            "user_id", "first_name", "last_name", "email", "mobile",
            "whatsapp_number", "pincode", "payment_type", "upi_number",
            "is_active", "blocked_status", "level",
            "profile", "kyc", "useraccountdetails"
        ]
        read_only_fields = ["user_id", "level", "email"]

    def update(self, instance, validated_data):
         # Pop nested data
        profile_data = validated_data.pop("profile", None)
        kyc_data = validated_data.pop("kyc", None)
        account_data = validated_data.pop("useraccountdetails", None)

        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update profile
        if profile_data is not None:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()

        # Update KYC
        if kyc_data is not None:
            kyc, _ = KYC.objects.get_or_create(user=instance)
            for attr, value in kyc_data.items():
                setattr(kyc, attr, value)
            kyc.save()

        # Update account details
        if account_data is not None:
            account, _ = UserAccountDetails.objects.get_or_create(user=instance)
            for attr, value in account_data.items():
                setattr(account, attr, value)
            account.save()

        return instance
    
    def get_profile_image(self, obj):
        if hasattr(obj, "profile") and obj.profile.profile_image:
            request = self.context.get("request")
            return request.build_absolute_uri(obj.profile.profile_image.url) if request else obj.profile.profile_image.url
        return None

    def get_blocked_status(self, obj):
        return "Unblocked" if obj.is_active else "Blocked"
    

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
        """Recalculate level by walking up the referral chain"""
        try:
            level = 0
            visited = set()
            current = obj
            while getattr(current, "referred_by", None):
                rid = getattr(current.referred_by, "user_id", None)
                if not rid or rid in visited:
                    break
                visited.add(rid)
                level += 1
                current = current.referred_by
            return level
        except Exception:
            return 0

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