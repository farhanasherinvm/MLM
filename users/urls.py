from django.urls import path
from .views import UserRegistrationView, login_view, forgot_password, reset_password_link
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('register/', UserRegistrationView.as_view(), name='user-register'),
    path("login/", login_view, name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("forgot-password/", forgot_password, name="forgot-password"),
    path("reset-password-link/", reset_password_link, name="reset-password-link"),
]
