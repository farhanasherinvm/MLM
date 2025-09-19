from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PaymentReportViewSet, DashboardReportViewSet, UserReportViewSet, UserLatestReportView, SendRequestReport, AUCRequest, LevelUsers

router = DefaultRouter()
router.register(r'payments', PaymentReportViewSet)
router.register(r'dashboard', DashboardReportViewSet, basename='dashboard')

router.register(r'user-report', UserReportViewSet, basename='user-report')

urlpatterns = [
    path('', include(router.urls),),
    path('user-latest-report/', UserLatestReportView.as_view(), name='user-latest-report'),
    path('send-request-report/', SendRequestReport.as_view(), name='send-request-report'),
    path('auc-request/', AUCRequest.as_view(), name='auc-request'),
    path('level-users/', LevelUsers.as_view(), name='level-users'),
]