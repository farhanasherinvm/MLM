from rest_framework import generics, permissions
from .models import Profile
from .serializers import ProfileSerializer
from rest_framework.response import Response
from .models import KYC
from .serializers import KYCSerializer
from rest_framework.views import APIView
from .serializers import ReferralSerializer
from django.db.models import Q
from django.contrib.auth import get_user_model

from rest_framework.permissions import IsAuthenticated

from .serializers import ReferralListSerializer
from .utils import get_all_referrals
from rest_framework.permissions import IsAdminUser
from django.utils.dateparse import parse_date

from django.utils.timezone import make_aware, is_naive
from datetime import datetime

CustomUser = get_user_model()





class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Fetch profile of currently logged-in user
        return self.request.user.profile


class KYCView(generics.RetrieveUpdateAPIView):
    serializer_class = KYCSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        #only one KYC
        obj, created = KYC.objects.get_or_create(user=self.request.user)
        return obj


class ReferralView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        referral_id = user.user_id  

        serializer = ReferralSerializer(data={"referral_id": referral_id})
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data)




class ReferralListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        all_referrals = get_all_referrals(user, max_level=6)

        # --- Filters from query params ---
        email = request.query_params.get("email")
        status = request.query_params.get("status")  # all / active / inactive
        user_id = request.query_params.get("user_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit")  # 10, 20, 60, etc.

        # Filter by email
        if email:
            all_referrals = [r for r in all_referrals if email.lower() in r.email.lower()]

        # Filter by status
        if status and status.lower() != "all":
            if status.lower() == "active":
                all_referrals = [r for r in all_referrals if r.is_active]
            elif status.lower() == "inactive":
                all_referrals = [r for r in all_referrals if not r.is_active]

        # Filter by user_id
        if user_id:
            all_referrals = [r for r in all_referrals if r.user_id == user_id]

        # Filter by joining date
        if start_date:
            start_date_parsed = parse_date(start_date)
            if start_date_parsed:
                all_referrals = [
                    r for r in all_referrals
                    if r.date_of_joining and r.date_of_joining.date() >= start_date_parsed
                ]

        if end_date:
            end_date_parsed = parse_date(end_date)
            if end_date_parsed:
                all_referrals = [
                    r for r in all_referrals
                    if r.date_of_joining and r.date_of_joining.date() <= end_date_parsed
                ]

        # --- Sort by recent joiners safely ---
        def get_joined_date(u):
            if u.date_of_joining:
                dt = u.date_of_joining
                if is_naive(dt):
                    dt = make_aware(dt)
                return dt
            return datetime.min.replace(tzinfo=None)  # users without date go last

        all_referrals.sort(key=get_joined_date, reverse=True)

        # Apply limit
        if limit:
            try:
                limit = int(limit)
                all_referrals = all_referrals[:limit]
            except ValueError:
                pass  # ignore invalid limit

        # Serialize and return
        serializer = ReferralListSerializer(all_referrals, many=True)
        return Response(serializer.data)
class AdminHomeView(APIView):
    permission_classes = [IsAdminUser]  
    def get(self, request):
        total_users = CustomUser.objects.count()

        data = {
            "total_users": total_users,
        }
        return Response(data)



