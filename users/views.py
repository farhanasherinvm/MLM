import string, random, razorpay
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.permissions import IsAuthenticated, BasePermission, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework_simplejwt.tokens import RefreshToken
from django.db.models import Q
from datetime import datetime
from reportlab.lib.pagesizes import A4
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import (
    RegistrationSerializer, LoginSerializer,
    RazorpayVerifySerializer,RazorpayOrderSerializer,
    ResetPasswordSerializer, ForgotPasswordSerializer, 
    AdminAccountSerializer, UserAccountDetailsSerializer, 
    UploadReceiptSerializer,  UserFullNameSerializer,
    SendOTPSerializer, VerifyOTPSerializer,
    )
from .permissions import IsProjectAdmin
from .utils import validate_sponsor, export_users_csv, export_users_pdf
from django.utils.crypto import get_random_string
from rest_framework.permissions import IsAdminUser
from profiles.models import Profile
from rest_framework.pagination import PageNumberPagination
# import admin serializer from profiles
from profiles.serializers import AdminUserListSerializer, AdminUserDetailSerializer, AdminNetworkUserSerializer
import logging
from django.db import IntegrityError, transaction
from users.utils import generate_next_placementid
from users.utils import assign_placement_id
from users.utils import create_and_send_otp
from users.utils import safe_send_mail

def generate_next_userid():
    while True:
        random_part = "".join(random.choices(string.digits, k=6))
        user_id = f"WS{random_part}"
        if not CustomUser.objects.filter(user_id=user_id).exists():
            return user_id

# inside users/views.py - replace existing SendOTPView with this:

class SendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()

        if CustomUser.objects.filter(email__iexact=email).exists():
            return Response({"error": "Email already registered."}, status=status.HTTP_400_BAD_REQUEST)

        ev, sent, error, provider_info = create_and_send_otp(email)

        # Build response for debugging on live server
        if sent:
            response = {
                "message": "OTP generated successfully.",
                "sent": True,
                "transport": provider_info.get("transport") if isinstance(provider_info, dict) else provider_info,
                "provider_info": provider_info,
            }
            # include OTP only in debug mode or if you explicitly want it for testing
            if getattr(settings, "DEBUG", False):
                response["debug_otp"] = ev.otp_code if ev else None
            return Response(response, status=status.HTTP_200_OK)
        else:
            response = {
                "message": "OTP generated but sending failed.",
                "sent": False,
                "error": error,
                "transport": provider_info.get("transport") if isinstance(provider_info, dict) else provider_info,
                "provider_info": provider_info,
                "otp": ev.otp_code if ev else None  # include for immediate testing
            }
            return Response(response, status=status.HTTP_200_OK)
    
class VerifyOTPView(APIView):
    """
    Verify the OTP for an email address.
    Request body: { "email": "...", "otp_code": "123456" }
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].strip().lower()
        otp_code = serializer.validated_data["otp_code"].strip()

        # Find latest non-verified record for this email
        ev = EmailVerification.objects.filter(email__iexact=email, is_verified=False).order_by("-created_at").first()
        if not ev:
            return Response({"error": "No OTP request found for this email. Please request OTP first."}, status=status.HTTP_400_BAD_REQUEST)

        if ev.is_expired():
            return Response({"error": "OTP expired. Please request a new OTP."}, status=status.HTTP_400_BAD_REQUEST)

        # Optionally enforce max attempts
        max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        if ev.attempts >= max_attempts:
            return Response({"error": "Too many attempts. Please request a new OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if ev.otp_code == otp_code:
            ev.is_verified = True
            ev.save(update_fields=["is_verified"])
            return Response({"message": "Email verified successfully."}, status=status.HTTP_200_OK)
        else:
            ev.attempts += 1
            ev.save(update_fields=["attempts"])
            return Response({"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

class RegistrationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = RegistrationSerializer(data=request.data)
        if serializer.is_valid():
            payment = serializer.create_payment(serializer.validated_data)
            return Response(
                {
                    "registration_token": str(payment.registration_token),
                    "admin_account_details": AdminAccountSerializer(AdminAccountDetails.objects.first()).data if AdminAccountDetails.objects.exists() else {},
                    "message": "Choose payment method: Pay Now (Razorpay) or upload receipt with this token.",
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

class RazorpayOrderView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = RazorpayOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        try:
            payment = Payment.objects.get(registration_token=serializer.validated_data["registration_token"], status="Pending")
        except Payment.DoesNotExist:
            return Response({"error": "Invalid registration token"}, status=400)

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order = client.order.create({"amount": int(payment.amount * 100), "currency": "INR", "payment_capture": 1})

        payment.razorpay_order_id = order["id"]
        payment.save()

        return Response(
            {
                "order_id": order["id"],
                "amount": payment.amount,
                "currency": "INR",
                "razorpay_key": settings.RAZORPAY_KEY_ID,
            }
        )


class RazorpayVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        import logging
        from django.db import IntegrityError
        logger = logging.getLogger(__name__)

        logger.debug("🔹 RazorpayVerifyView called with data: %s", request.data)

        try:
            # Step 1: Validate serializer
            serializer = RazorpayVerifySerializer(data=request.data)
            if not serializer.is_valid():
                logger.error("❌ Serializer validation failed: %s", serializer.errors)
                return Response(serializer.errors, status=400)

            data = serializer.validated_data
            logger.debug("✅ Serializer valid. Data: %s", data)

            # Step 2: Lookup Payment
            try:
                payment = Payment.objects.get(
                    razorpay_order_id=data["razorpay_order_id"],
                    status="Pending"
                )
                logger.debug("✅ Payment %s found with status Pending", payment.id)
            except Payment.DoesNotExist:
                logger.error("❌ Payment not found for order_id=%s", data["razorpay_order_id"])
                return Response({"error": "Payment not found or already processed"}, status=404)

            # Step 3: Verify Razorpay signature (skip if TEST_MODE)
            if getattr(settings, "RAZORPAY_TEST_MODE", True):
                logger.debug("⚡ RAZORPAY_TEST_MODE=True, skipping signature verification")
                verification_ok = True
            else:
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                try:
                    params_dict = {
                        "razorpay_order_id": data["razorpay_order_id"],
                        "razorpay_payment_id": data["razorpay_payment_id"],
                        "razorpay_signature": data["razorpay_signature"],
                    }
                    client.utility.verify_payment_signature(params_dict)
                    verification_ok = True
                    logger.debug("✅ Razorpay signature verification passed")
                except Exception as e:
                    logger.exception("❌ Razorpay signature verification failed")
                    return Response({'error': 'Payment verification failed.'}, status=500)

            if not verification_ok:
                payment.status = "Failed"
                payment.save()
                logger.warning("❌ Verification failed, payment %s marked as Failed", payment.id)
                return Response({"error": "Signature verification failed"}, status=400)

            # Step 4: Load registration data
            reg_data = payment.get_registration_data() or {}
            logger.debug("📦 Registration data loaded: %s", reg_data)

            required_fields = ["email", "password", "first_name", "last_name"]
            missing_fields = [f for f in required_fields if not reg_data.get(f)]
            if missing_fields:
                logger.error("❌ Missing fields in registration data: %s", missing_fields)
                return Response(
                    {"error": f"Missing required fields in registration data: {', '.join(missing_fields)}"},
                    status=400
                )

            # Step 5: Validate sponsor
            sponsor_id = reg_data.get("sponsor_id")
            sponsor = None
            if sponsor_id:
                if not validate_sponsor(sponsor_id):
                    logger.error("❌ Invalid sponsor ID: %s", sponsor_id)
                    return Response({"error": "Invalid sponsor ID"}, status=400)
                sponsor = CustomUser.objects.filter(user_id=sponsor_id).first()
                logger.debug("✅ Sponsor validated: %s", sponsor_id)

            # Step 6: Generate placement and user IDs
            placement_id = generate_next_placementid() if sponsor else None
            user_id = generate_next_userid()
            logger.debug("🆕 Generated user_id=%s, placement_id=%s", user_id, placement_id)

            defaults = {
                "user_id": user_id,
                "sponsor_id": sponsor.user_id if sponsor else None,
                "placement_id": placement_id,
                "first_name": reg_data.get("first_name", ""),
                "last_name": reg_data.get("last_name", ""),
                "mobile": reg_data.get("mobile", ""),
                "whatsapp_number": reg_data.get("whatsapp_number", ""),
                "pincode": reg_data.get("pincode", ""),
                "payment_type": reg_data.get("payment_type", "Other"),
                "upi_number": reg_data.get("upi_number", ""),
            }

            # Step 7: Create user
            try:
                user, created = CustomUser.objects.get_or_create(
                    email=reg_data.get("email"),
                    defaults=defaults
                )
                logger.debug("✅ User %s retrieved/created. created=%s", user.id, created)
            except IntegrityError as ie:
                logger.exception("❌ IntegrityError while creating user")
                return Response({"error": "Database integrity error while creating user.",
                                 "details": str(ie)}, status=409)
            except Exception as e:
                logger.exception("❌ Unexpected error while creating user")
                return Response({"error": "User creation failed.", "details": str(e)}, status=500)

            # Step 8: Set password for new users
            if created:
                raw_password = reg_data.get("password")
                if not raw_password:
                    logger.error("❌ Password missing in registration data for new user")
                    return Response({"error": "Password missing in registration data."}, status=400)
                user.set_password(raw_password)
                user.save()
                logger.debug("✅ Password set for new user %s", user.user_id)

            # Step 9: Update payment record
            payment.user = user
            payment.status = "Verified"
            payment.razorpay_payment_id = data.get("razorpay_payment_id")
            payment.razorpay_signature = data.get("razorpay_signature")
            payment.save()
            logger.debug("✅ Payment %s updated and linked to user %s", payment.id, user.user_id)

            # Step 10: Send welcome email
            if created:
                sent = safe_send_mail(
                    subject="Your MLM UserID",
                    message=f"Your UserID is {user.user_id}\nYour Placement ID is {user.placement_id}",
                    recipient_list=[user.email],
                )
                logger.debug("📧 Email send attempted to %s. Success=%s", user.email, sent)

            return Response({
                "message": "Payment verified and user created" if created else "Payment verified, user already exists",
                "user_id": user.user_id,
                "placement_id": user.placement_id,
            })

        except Exception as outer_exc:
            logger.exception("❌ Unhandled exception in RazorpayVerifyView.post")
            return Response({"error": "Internal server error", "details": str(outer_exc)}, status=500)

   
class UploadReceiptView(APIView):
    permission_classes = [AllowAny]
    def post(self, request, *args, **kwargs):
        serializer = UploadReceiptSerializer(data=request.data)
        if serializer.is_valid():
            payment = serializer.save()
            return Response(
                {
                    "message": "Receipt uploaded successfully. Awaiting admin verification.",
                    "payment_id": payment.id,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
      
class AdminVerifyPaymentView(APIView):
    permission_classes = [IsProjectAdmin]

    def get(self, request, *args, **kwargs):
        """List payments (filterable by status)"""
        status_filter = request.query_params.get("status")

        payments = Payment.objects.all()
        if status_filter in ["Pending", "Verified", "Failed"]:
            payments = payments.filter(status=status_filter)
        data = [
            {
                "id": p.id,
                "amount": str(p.amount),
                "status": p.status,
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M"),
                "receipt": request.build_absolute_uri(p.receipt.url) if p.receipt else None,
                "user_email": p.get_registration_data().get("email"),
            }
            for p in payments
        ]
        return Response({
            "count": payments.count(),
            "status_filter": status_filter or "All",
            "payments": data
        })

    def post(self, request, payment_id, *args, **kwargs):
        """Verify or mark payment failed"""
        payment = get_object_or_404(Payment, id=payment_id)
        reg_data = payment.get_registration_data()

        status_choice = request.data.get("status")
        if status_choice not in ["Verified", "Failed"]:
            return Response({"error": "Invalid status"}, status=400)

        if status_choice == "Failed":
            payment.status = "Failed"
            payment.save()

            email = reg_data.get("email")
            if email:
                safe_send_mail(
                subject="Payment unsuccessful",
                message=f"Hello {email},\n\nUnfortunately, your payment has failed. Please try again.",
                recipient_list=[email],
                )
            return Response({"message": "Payment marked as Failed"}, status=200)

        # Verified flow
        payment.status = "Verified"
        payment.save()

        if not payment.user:
            reg_data = payment.get_registration_data()
            sponsor_id = reg_data.get("sponsor_id")

            user, created = CustomUser.objects.get_or_create(
                email=reg_data["email"],
                defaults={
                    "user_id": generate_next_userid(),
                    "password": reg_data["password"],
                    "sponsor_id": reg_data.get("sponsor_id"),
                    "placement_id": reg_data.get("placement_id"),
                    "first_name": reg_data["first_name"],
                    "last_name": reg_data["last_name"],
                    "mobile": reg_data["mobile"],
                    "whatsapp_number": reg_data["whatsapp_number"],
                    "pincode": reg_data["pincode"],
                    "payment_type": reg_data["payment_type"],
                    "upi_number": reg_data["upi_number"],
                }
            )
            if created:
                user.set_password(reg_data["password"])
                user.save()

            payment.user = user
            payment.save()

            if created:
                safe_send_mail(
                    subject="Your MLM User ID",
                    message=f"Hello {user.user_id},\n\nYour payment has been verified. Your User ID is: {user.user_id}",
                    recipient_list=[user.email],
                    )
            return Response({
                "message": (
                    f"Payment verified and user created."
                    f"A mail with the User ID {user.user_id} has been sent to {user.email}"
                    if created else "Payment verified, user already exists"
                ),
                "user_id": user.user_id
            })

        return Response({"message": "Payment verified successfully"})

    
class AdminAccountAPIView(APIView):
    permission_classes = [AllowAny]
    def get_permissions(self):
        if self.request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def get(self, request):
        details = AdminAccountDetails.objects.last()
        if not details:
            return Response({}, status=200)
        return Response(AdminAccountSerializer(details).data)

    def post(self, request):
        details = AdminAccountDetails.objects.last()
        serializer = AdminAccountSerializer(instance=details, data=request.data, partial=True)
        if serializer.is_valid():
            obj = serializer.save()
            return Response(AdminAccountSerializer(obj).data)
        return Response(serializer.errors, status=400)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data["user"]

            refresh = RefreshToken.for_user(user)

            return Response({
                "message": "Login successful",
                "user_id": user.user_id,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if not refresh_token:
                return Response({"error": "Refresh token is required."}, status=400)

            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response({"message": "Successfully logged out."}, status=200)

        except Exception:
            return Response({"error": "Invalid token or already logged out."}, status=400)


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token = get_random_string(48)
        PasswordResetToken.objects.create(user=user, token=token)
        reset_link = f"https://winnersclubx.netlify.app/api/reset-password/?token={token}"

        safe_send_mail(
            subject="Reset Your Password",
            message=f"Click this link to reset your password:\n{reset_link}",
            recipient_list=[user.email],
        )
        return Response({"message": f"Password reset link send to {user.user_id}'s email", "reset_link": reset_link})
        
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        token = request.query_params.get('token') or request.data.get('token')
        serializer = ResetPasswordSerializer(data=request.data, context={"token": token})
        serializer.is_valid(raise_exception=True)
        reset_token = serializer.validated_data['reset_token']
        user = reset_token.user

        user.set_password(serializer.validated_data['new_password'])
        user.save()
        reset_token.is_used = True
        reset_token.save()

        safe_send_mail(
            subject="Password Reset Successful",
            message="Your password has been reset. You can now login using your new password.",
            recipient_list=[user.email],
        )
        return Response({"message": f"Password for {user.user_id} reset successfully."})
    
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("re_enter_password")

        if not user.check_password(old_password):
            return Response({"error": "Old password is incorrect."},
                            status=status.HTTP_400_BAD_REQUEST)

        if new_password != confirm_password:
            return Response({"error": "Passwords do not match."},
                            status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()

        return Response({"message": "Password updated successfully."},
                        status=status.HTTP_200_OK)
    
class UserAccountDetailsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]  # for file upload

    def get(self, request):
        """Get current user account details"""
        try:
            details = UserAccountDetails.objects.get(user=request.user)
            return Response(UserAccountDetailsSerializer(details).data)
        except UserAccountDetails.DoesNotExist:
            return Response({"message": "Account details not found"}, status=404)
    
    def post(self, request):
        """Create or update account details"""
        user = request.user
        data = request.data.copy()

        if not data.get("upi_number"):
            data["upi_number"] = user.upi_number
        if not data.get("upi_type"):
            data["upi_type"] = user.payment_type

        try:
            details = UserAccountDetails.objects.get(user=user)
            serializer = UserAccountDetailsSerializer(details, data=data, partial=True)
        except UserAccountDetails.DoesNotExist:
            serializer = UserAccountDetailsSerializer(data=data)

        if serializer.is_valid():
            account_details = serializer.save(user=user)
            return Response(UserAccountDetailsSerializer(account_details).data, status=200)

        return Response(serializer.errors, status=400)

    
    def put(self, request):
        user = request.user
        data = request.data.copy()

        try:
            details = user.useraccountdetails
        except UserAccountDetails.DoesNotExist:
            return Response({"error": "Account details not found"}, status=404)
        
        if not data.get("upi_number"):
            data["upi_number"] = details.upi_number or user.upi_number
        if not data.get("upi_type"):
            data["upi_type"] = details.upi_type or user.payment_type

        serializer = UserAccountDetailsSerializer(details, data=data, partial=True)
        if serializer.is_valid():
            account_details = serializer.save(user=user)
            return Response(UserAccountDetailsSerializer(account_details).data, status=200)

        return Response(serializer.errors, status=400)
    
class IsProjectAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin_user)

class AdminUserPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100

def apply_search_and_filters(queryset, request):
    """Reusable function for search, status, date filters"""
    # Search
    search = request.query_params.get("search") or request.data.get("search")
    if search:
        parts = search.strip().split()
        if len(parts) >= 2:
            queryset = queryset.filter(
                Q(user_id__icontains=search) |
                (Q(first_name__icontains=parts[0]) & Q(last_name__icontains=" ".join(parts[1:])))
            )
        else:
            queryset = queryset.filter(
                Q(user_id__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )
     # Status filter
    status_filter = request.query_params.get("status") or request.data.get("status")
    if status_filter == "active":
        queryset = queryset.filter(is_active=True)
    elif status_filter == "blocked":
        queryset = queryset.filter(is_active=False)

    # Date filters
    start_date = request.query_params.get("start_date") or request.data.get("start_date")
    end_date = request.query_params.get("end_date") or request.data.get("end_date")
    date_format = "%Y-%m-%d"
    if start_date:
        try:
            start = datetime.strptime(start_date, date_format)
            queryset = queryset.filter(date_of_joining__gte=start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, date_format)
            queryset = queryset.filter(date_of_joining__lte=end)
        except ValueError:
            pass

    # Level filter (post-query, but still controlled here)
    level_filter = request.query_params.get("level") or request.data.get("level")
    if level_filter:
        try:
            level_filter = int(level_filter)
            queryset = [u for u in queryset if getattr(u, "level", None) == level_filter]
        except (ValueError, TypeError):
            pass

    return queryset
class AdminListUsersView(APIView):
    """List, search, filter, paginate, and export users"""
    permission_classes = [IsAdminUser]

    def get_queryset(self, request):
        # Preload profile to avoid N+1 queries
        return CustomUser.objects.select_related("profile").all()

    def get_export_format(self, request):
        return (request.query_params.get("export") or "").lower()

    def get(self, request):
        return self.handle_request(request)

    def post(self, request):
        return self.handle_request(request)

    def handle_request(self, request):
        queryset = self.get_queryset(request)
        queryset = apply_search_and_filters(queryset, request)
        export_format = self.get_export_format(request)

        if export_format == "csv":
            return export_users_csv(queryset, filename="users.csv")
        elif export_format == "pdf":
            return export_users_pdf(queryset, filename="users.pdf")

        # Pagination
        paginator = AdminUserPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = AdminUserListSerializer(page, many=True, context={"request": request})

        return paginator.get_paginated_response(serializer.data)

class AdminUserListView(APIView):
    permission_classes = [IsProjectAdmin]

    def get_search_query(self, request):
        return (request.query_params.get("search") or request.data.get("search") or "").strip()

    def get_export_format(self, request):
        return request.query_params.get("export", "").lower()  # "csv" or "pdf"

    def get(self, request):
        search_query = self.get_search_query(request)
        export_format = self.get_export_format(request)
        return self.search_and_respond(search_query, export_format, request)

    def post(self, request):
        search_query = self.get_search_query(request)
        export_format = self.get_export_format(request)
        return self.search_and_respond(search_query, export_format, request)

    def search_and_respond(self, search_query, export_format, request):
        users = CustomUser.objects.select_related("profile").all()

        # Filter by start_date / end_date
        start_date = request.query_params.get("start_date") or request.data.get("start_date")
        end_date = request.query_params.get("end_date") or request.data.get("end_date")
        if start_date:
            users = users.filter(date_of_joining__gte=start_date)
        if end_date:
            users = users.filter(date_of_joining__lte=end_date)

        # Apply search / status / level filters    
        users = apply_search_and_filters(users, request)

        # Export if requested
        if export_format == "csv":
            return export_users_csv(users, filename="users.csv")
        elif export_format == "pdf":
            return export_users_pdf(users, filename="users.pdf")

        # Paginate
        paginator = AdminUserPagination()
        page = paginator.paginate_queryset(users, request)
        serializer = AdminUserListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)    
class AdminUserDetailView(APIView):
    """
    Allows project admin to view & edit full user + profile details
    """
    permission_classes = [IsProjectAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, user_id):
        try:
            user = CustomUser.objects.select_related("profile").get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        serializer = AdminUserDetailSerializer(user, context={"request": request})
        return Response(serializer.data, status=200)

    def put(self, request, user_id):
        try:
            user = CustomUser.objects.select_related("profile").get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        serializer = AdminUserDetailSerializer(user, data=request.data, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({"message": f"User {user.user_id} updated successfully"})
        return Response(serializer.errors, status=400)

class AdminToggleUserActiveView(APIView):
    """
    Project admin can toggle a user's active/block status.
    """
    permission_classes = [IsProjectAdmin]

    def patch(self, request, user_id):
        try:
            user = CustomUser.objects.get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Toggle the is_active flag
        user.is_active = not user.is_active
        user.save()
        state = "unblocked" if user.is_active else "blocked"
        return Response({"message": f"User {user.user_id} {state} successfully", "is_active": user.is_active})


class AdminResetUserPasswordView(APIView):
    """
    Project admin can reset a user's password.
    """
    permission_classes = [IsProjectAdmin]

    def post(self, request, user_id):
        try:
            user = CustomUser.objects.get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")
        if not new_password or new_password != confirm_password:
            return Response({"error": "Passwords do not match"}, status=400)

        user.set_password(new_password)
        user.save()

        # Optional: Send email notification
        safe_send_mail(
            subject="Your Password Has Been Reset",
            message=f"Hello {user.first_name},\n\nYour password has been reset by the admin. Your new password is: {new_password}",
            recipient_list=[user.email],
        )
        return Response({"message": f"Password reset successfully for {user.user_id}"})

   
class AdminExportUsersCSVView(APIView):
    """
    Export users as CSV using utils.py helper.
    """
    permission_classes = [IsProjectAdmin]

    def get(self, request, *args, **kwargs):
        users = CustomUser.objects.select_related("profile").all()
        users = apply_search_and_filters(users, request)
        return export_users_csv(users, filename="admin_users_export.csv")

class AdminExportUsersPDFView(APIView):
    """
    Export users as PDF using utils.py helper.
    """
    permission_classes = [IsProjectAdmin]

    def get(self, request, *args, **kwargs):
        users = CustomUser.objects.select_related("profile").all()
        users = apply_search_and_filters(users, request)
        return export_users_pdf(users, filename="admin_users_export.pdf", title="Admin Users Report")
     
class AdminViewProfileImageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        if not request.user.is_admin_user:
            return Response({"error": "Not authorized"}, status=403)

        try:
            profile = Profile.objects.get(user__user_id=user_id)
        except Profile.DoesNotExist:
            return Response({"error": "User profile not found"}, status=404)

        if not profile.profile_image:
            return Response({"error": "No profile image found"}, status=404)

        return FileResponse(profile.profile_image.open("rb"), content_type="image/png")
    
class AdminNetworkView(APIView):
    """Admin view for network users, counts, search, filter, and export"""
    permission_classes = [IsProjectAdmin]

    def get_queryset(self, request):
        return apply_search_and_filters(CustomUser.objects.select_related("profile").all(), request)

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset(request)

        # Counts before level filtering
        total_downline = len(queryset)
        active_count = sum(1 for u in queryset if u.is_active)
        blocked_count = sum(1 for u in queryset if not u.is_active)

        export_format = request.query_params.get("export")
        if export_format == "csv":
            return export_users_csv(queryset, filename="network_users.csv")
        if export_format == "pdf":
            return export_users_pdf(queryset, filename="network_users.pdf", title="Network Users Report")

        serializer = AdminNetworkUserSerializer(queryset, many=True, context={"request": request})
        return Response({
            "counts": {
                "total_downline": total_downline,
                "active_count": active_count,
                "blocked_count": blocked_count,
            },
            "users": serializer.data
        })  
class GetUserFullNameView(APIView):
    permission_classes = [AllowAny]

    def get_user_id(self, request):
        """Extract user_id from GET query or POST body"""
        if request.method == "GET":
            return request.query_params.get("user_id")
        if request.method == "POST":
            return request.data.get("user_id")
        return None

    def handle_request(self, user_id):
        if not user_id:
            return Response({"error": "user_id is required"}, status=400)

        try:
            user = CustomUser.objects.get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "Invalid user_id"}, status=404)

        full_name = f"{user.first_name} {user.last_name}".strip() or user.user_id
        serializer = UserFullNameSerializer({"user_id": user.user_id, "full_name": full_name})
        return Response(serializer.data, status=200)

    def get(self, request):
        user_id = self.get_user_id(request)
        return self.handle_request(user_id)

    def post(self, request):
        user_id = self.get_user_id(request)
        return self.handle_request(user_id)
