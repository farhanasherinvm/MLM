from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LevelViewSet, UserLevelViewSet, LevelCompletionViewSet
from . import views

router = DefaultRouter()
router.register(r'levels', LevelViewSet)
router.register(r'user-levels', UserLevelViewSet)
router.register(r'level-completion', LevelCompletionViewSet, basename='level-completion')

urlpatterns = [
    path('', include(router.urls)),
    path('razorpay-order-level/', views.RazorpayOrderForLevelView.as_view(), name='razorpay-order-level'),
    path('razorpay-verify-level/', views.RazorpayVerifyForLevelView.as_view(), name='razorpay-verify-level')
]