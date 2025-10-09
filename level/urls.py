from django.urls import path, include
from rest_framework.routers import DefaultRouter
from level.views import (
    LevelViewSet, UserLevelViewSet, RazorpayOrderForLevelView,
    RazorpayVerifyForLevelView, ManualPaymentView, LevelPaymentViewSet,
    LevelCompletionViewSet,InitiatePaymentView, CreateDummyUsers, UpdateLinkedUserIdView, RecipientPaymentViewSet, DummyUserViewSet , AdminDummyUserControlView
    , PmfStatusView, PmfOrderView, PmfVerifyView, PmfManualPaymentView, PmfPaymentViewSet
)

router = DefaultRouter()
router.register(r'levels', LevelViewSet,basename='levels')
router.register(r'user-levels', UserLevelViewSet,basename='user-levels')
router.register(r'level-payments', LevelPaymentViewSet,basename='level-payments')
router.register(r'level-completion', LevelCompletionViewSet,basename='level-completion')
router.register(r'recipient/payments', RecipientPaymentViewSet, basename='recipient-payments') 
router.register(r'dummy-users', DummyUserViewSet, basename='dummy-users')
router.register(r'pmf-payments', PmfPaymentViewSet, basename='pmf-payment')


urlpatterns = [
    path('', include(router.urls)),
    path('razorpay-order/', RazorpayOrderForLevelView.as_view(), name='razorpay-order'),
    path('razorpay-verify/', RazorpayVerifyForLevelView.as_view(), name='razorpay-verify'),
    path('manual-payment/', ManualPaymentView.as_view(), name='manual-payment'),
    path('initiate-payment/', InitiatePaymentView.as_view(), name='initiate-payment'),
    path('create-dummy-users/', CreateDummyUsers.as_view(), name='create_dummy_users'),
    path('update-level/<int:pk>/', UpdateLinkedUserIdView.as_view(), name='update_linked_user_id'),
    path('dummy-users/control/<int:pk>/', AdminDummyUserControlView.as_view(), name='dummy-user-control'),
    path('pmf/status/', PmfStatusView.as_view(), name='pmf-status-check'),
    path('pmf/order/', PmfOrderView.as_view(), name='pmf-order'),       
    path('pmf/verify/', PmfVerifyView.as_view(), name='pmf-verify'),
    path('pmf/manual-submit/', PmfManualPaymentView.as_view(), name='pmf-manual-submit'),

]