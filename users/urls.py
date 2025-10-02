from django.urls import path
from .views import *
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # path("register/", RegistrationView.as_view(), name="register"),
    path("register/", RegisterView.as_view(), name="register"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    # path("register/legacy/", RegistrationView.as_view(), name="register-legacy"),
    path("razorpay/order/", RazorpayOrderView.as_view(), name="razorpay-order"),
    path("razorpay/verify/", RazorpayVerifyView.as_view(), name="razorpay-verify"),
    path("upload-receipt/", UploadReceiptView.as_view(), name="upload-receipt"),
    path("admin/verify-payment/", AdminVerifyPaymentView.as_view(), name="admin-list-pending-payments"),
    path("admin/verify-payment/<int:payment_id>/", AdminVerifyPaymentView.as_view(), name="admin-verify-payment"),
    path("admin-account/", AdminAccountAPIView.as_view(), name="admin-account"),
    path("login/", LoginView.as_view(), name="login"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("account-details/", UserAccountDetailsView.as_view(), name="account-details"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("admin/users/", AdminListUsersView.as_view(), name="admin-list-users"),
    path("admin/users/compact/", AdminUserListView.as_view(), name="admin-compact-users"),
    path("admin/users/<str:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("admin/users/<str:user_id>/toggle-active/", AdminToggleUserActiveView.as_view(), name="admin-toggle-user-active"),
    path("admin/users/<str:user_id>/reset-password/", AdminResetUserPasswordView.as_view(), name="admin-reset-user-password"),
    path("admin/users/export/csv/", AdminExportUsersCSVView.as_view(), name="admin-export-users-csv"),
    path("admin/users/export/pdf/", AdminExportUsersPDFView.as_view(), name="admin-export-users-pdf"),
    path("admin/users/<str:user_id>/profile-image/", AdminViewProfileImageView.as_view()),
    path('admin/network/', AdminNetworkView.as_view(), name='admin-network'),
    path("users/fullname/", GetUserFullNameView.as_view(), name="get-user-fullname"),
]
