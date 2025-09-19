from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PaymentReportViewSet, DashboardReportViewSet, UserReportViewSet, UserLatestReportView

router = DefaultRouter()
router.register(r'payments', PaymentReportViewSet)
router.register(r'dashboard', DashboardReportViewSet, basename='dashboard')

router.register(r'user-report', UserReportViewSet, basename='user-report')

urlpatterns = [
    path('', include(router.urls),),
    path('user-latest-report/', UserLatestReportView.as_view(), name='user-latest-report'),
]