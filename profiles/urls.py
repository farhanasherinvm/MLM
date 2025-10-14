from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from .views import ProfileView,KYCView,ReferralView,ReferralListView,AdminHomeView,ReferralExportView,CurrentUserProfileView,FreePlacementListView



urlpatterns = [
    path('profile/', ProfileView.as_view(), name='profile-detail-update'),
    path("kyc/", KYCView.as_view(), name="kyc"), #only put and patch are allowed
    path("referral/", ReferralView.as_view(), name="referral"),#get refferal link
    path("referrals/list/", ReferralListView.as_view(), name="referrals"),
    path("admin/home/", AdminHomeView.as_view(), name="admin-home"),
    path('referrals/export/', ReferralExportView.as_view(), name="referrals-export"),
    path('me/', CurrentUserProfileView.as_view(), name='current-user-profile'),
    path('free-placements/', FreePlacementListView.as_view(), name='free-placements'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
