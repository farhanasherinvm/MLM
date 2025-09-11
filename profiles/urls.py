from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from .views import ProfileView,KYCView,ReferralView

urlpatterns = [
    path('profile/', ProfileView.as_view(), name='profile-detail-update'),
    path("kyc/", KYCView.as_view(), name="kyc"), #only put and patch are allowed
     path("referral/", ReferralView.as_view(), name="referral"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
