from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PaymentReportViewSet, DashboardReportViewSet

router = DefaultRouter()
router.register(r'payments', PaymentReportViewSet)
router.register(r'dashboard', DashboardReportViewSet, basename='dashboard')

urlpatterns = [
    path('', include(router.urls)),
]