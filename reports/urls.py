from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PaymentReportViewSet, DashboardReportViewSet, UserReportViewSet, UserLatestReportView
from .views import SendRequestReport, AUCReport, PaymentReport, LevelUsersReport,AllUserBonusSummaryListView, SingleUserBonusSummaryView

router = DefaultRouter()
router.register(r'payments', PaymentReportViewSet)
router.register(r'dashboard', DashboardReportViewSet, basename='dashboard')

router.register(r'user-report', UserReportViewSet, basename='user-report')

urlpatterns = [
    path('', include(router.urls)),
    path('user-latest-report/', UserLatestReportView.as_view(), name='user-latest-report'),
    path('send-request-report/', SendRequestReport.as_view(), name='send-request-report'),
    path('auc-report/', AUCReport.as_view(), name='auc-report'),
    path('payment-report/', PaymentReport.as_view(), name='payment-report'),
    path('level-users-report/', LevelUsersReport.as_view(), name='level-users-report'),
    path('listbonus/', AllUserBonusSummaryListView.as_view(), name='all-user-bonus-list'),
    path('singlebonus/<str:user_id>/', SingleUserBonusSummaryView.as_view(), name='single-user-bonus-detail'),


    
]