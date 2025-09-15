from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LevelViewSet, UserLevelViewSet
from . import views

router = DefaultRouter()
router.register(r'levels', LevelViewSet)
router.register(r'user-levels', UserLevelViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('razorpay-order-level/', views.RazorpayOrderForLevelView.as_view(), name='razorpay-order-level'),
    path('razorpay-verify-level/', views.RazorpayVerifyForLevelView.as_view(), name='razorpay-verify-level')
]