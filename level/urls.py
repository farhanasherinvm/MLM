from django.urls import path, include
from rest_framework.routers import DefaultRouter
from level.views import (
    LevelViewSet, UserLevelViewSet, RazorpayOrderForLevelView,
    RazorpayVerifyForLevelView, ManualPaymentView, LevelPaymentViewSet,
    LevelCompletionViewSet,InitiatePaymentView
)

router = DefaultRouter()
router.register(r'levels', LevelViewSet,basename='levels')
router.register(r'user-levels', UserLevelViewSet,basename='user-levels')
router.register(r'level-payments', LevelPaymentViewSet,basename='level-payments')
router.register(r'level-completion', LevelCompletionViewSet,basename='level-completion')

urlpatterns = [
    path('', include(router.urls)),
    path('razorpay-order/', RazorpayOrderForLevelView.as_view(), name='razorpay-order'),
    path('razorpay-verify/', RazorpayVerifyForLevelView.as_view(), name='razorpay-verify'),
    path('manual-payment/', ManualPaymentView.as_view(), name='manual-payment'),
    path('initiate-payment/', InitiatePaymentView.as_view(), name='initiate-payment'),

]