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
        referral_link = {user.user_id}
        serializer = ReferralSerializer({"referral_url": referral_link})
        return Response(serializer.data)
  



class ReferralListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        referrals = get_all_referrals(user, 6)

        # 🔎 Search filters
        email = request.query_params.get("email")
        status = request.query_params.get("status")

        if email:
            referrals = [r for r in referrals if email.lower() in r.email.lower()]
        if status:
            if status.lower() == "active":
                referrals = [r for r in referrals if r.is_active]
            elif status.lower() == "inactive":
                referrals = [r for r in referrals if not r.is_active]

        serializer = ReferralListSerializer(referrals, many=True)
        return Response(serializer.data)



class AdminHomeView(APIView):
    permission_classes = [IsAdminUser]  
    def get(self, request):
        total_users = CustomUser.objects.count()

        data = {
            "total_users": total_users,
        }
        return Response(data)
