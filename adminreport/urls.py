from django.urls import path
from .views import (
    AdminAUCReportView,
    AdminSendRequestView,
    AdminPaymentReportView,
    AdminNotificationsView
)

urlpatterns = [
    path('auc-report/', AdminAUCReportView.as_view(), name='admin-auc-report'),
    path('send-requests/', AdminSendRequestView.as_view(), name='admin-send-requests'),
    path('payments/', AdminPaymentReportView.as_view(), name='admin-payment-report'),
    path('notifications/', AdminNotificationsView.as_view(), name='admin-notifications'),
]