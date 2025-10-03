import string, random, razorpay, os
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
from datetime import datetime, timedelta
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import (
    RegistrationSerializer, LoginSerializer,
    RazorpayVerifySerializer,RazorpayOrderSerializer,
    ResetPasswordSerializer, ForgotPasswordSerializer, 
    AdminAccountSerializer, UserAccountDetailsSerializer, 
    UploadReceiptSerializer,  UserFullNameSerializer,
    VerifyOTPSerializer,
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
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

# Safe Razorpay client initialization (only once)
try:
    import razorpay as _razorpay
    if getattr(settings, "RAZORPAY_KEY_ID", None) and getattr(settings, "RAZORPAY_KEY_SECRET", None):
        razorpay_client = _razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    else:
        razorpay_client = None
    razorpay = _razorpay
except Exception as e:
    logger.warning("Razorpay not available: %s", e)
    razorpay = None
    razorpay_client = None

def safe_send_mail(subject, message, recipient_list, from_email=None, otp=None):
    """
    Send mail safely. If SMTP fails or times out, log error and continue.
    Additionally, log OTP to DB/logs if provided.
    """
    from django.core.mail import get_connection, EmailMessage
    import logging, socket

    logger = logging.getLogger(__name__)

    try:
        # Ensure timeout for SMTP connections
        socket.setdefaulttimeout(5)

        connection = get_connection(
            fail_silently=True,
            timeout=5
        )
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
            to=recipient_list,
            connection=connection,
        )
        email.send(fail_silently=True)
        logger.info(f"✅ Email sent to {recipient_list}: {subject}")
    except Exception as e:
        logger.error(f"❌ Email sending failed for {recipient_list}: {e}")

    # Always log OTPs explicitly if present
    if otp:
        logger.warning(f"🔐 OTP for {recipient_list}: {otp}")


def generate_next_userid():
    while True:
        random_part = "".join(random.choices(string.digits, k=6))
        user_id = f"WS{random_part}"
        if not CustomUser.objects.filter(user_id=user_id).exists():
            return user_id
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)

        otp = str(random.randint(100000, 999999))
        validated["otp"] = otp
        validated["otp_created_at"] = datetime.utcnow().isoformat()

        try:
            payment = Payment.objects.create(amount=validated["amount"])
            payment.set_registration_data(validated)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

        # ✅ Log OTP into Payment DB & logs even if email fails
        safe_send_mail(
            subject="Your Verification OTP",
            message=f"Your OTP for registration is: {otp}\nIt will expire in {getattr(settings, 'OTP_EXPIRY_MINUTES', 10)} minutes.",
            recipient_list=[validated["email"]],
            otp=otp,   # ✅ explicitly pass OTP for logging
        )

        return Response({
            "message": "Registered successfully. Please verify OTP sent to your email.",
            "email": validated["email"],
            "amount": str(payment.amount),
            "debug_otp": otp if settings.DEBUG else None  # ✅ show OTP in API only in DEBUG
        }, status=status.HTTP_201_CREATED)

class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        otp = serializer.validated_data["otp"].strip()

        try:
            payment = Payment.objects.filter(status="Pending").latest("created_at")
        except Payment.DoesNotExist:
            return Response({"error": "No pending registration found."}, status=404)

        reg_data = payment.get_registration_data()
        if not reg_data or reg_data.get("email").lower() != email:
            return Response({"error": "No matching registration found."}, status=404)

        if reg_data.get("otp") != otp:
            return Response({"error": "Invalid OTP."}, status=400)

        expiry_minutes = int(getattr(settings, "OTP_EXPIRY_MINUTES", 10))
        otp_time = datetime.fromisoformat(reg_data.get("otp_created_at"))
        if otp_time + timedelta(minutes=expiry_minutes) < datetime.utcnow():
            return Response({"error": "OTP expired. Please register again."}, status=400)

        reg_data["otp"] = ""
        payment.set_registration_data(reg_data)

        return Response({
            "message": "OTP verified successfully. Proceed to payment.",
            "registration_token": str(payment.registration_token),
            "amount": str(payment.amount),
        }, status=200)
               
class RazorpayOrderView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if razorpay_client is None:
            return Response({"error": "Razorpay not configured."}, status=503)

        serializer = RazorpayOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reg_token = serializer.validated_data["registration_token"]

        try:
            payment = Payment.objects.get(registration_token=reg_token, status="Pending")
        except Payment.DoesNotExist:
            return Response({"error": "Invalid or expired registration token."}, status=400)

        # Ensure amount exists and is numeric
        if payment.amount is None:
            logger.error("Payment %s has no amount set", payment.id)
            return Response({"error": "Payment amount not set"}, status=400)

        amount_paisa = int(float(payment.amount) * 100)

        try:
            order = razorpay_client.order.create({
                "amount": amount_paisa,
                "currency": "INR",
                "payment_capture": 1,
            })
        except Exception as e:
            logger.error("Razorpay order creation failed for Payment %s: %s", payment.id, e)
            payment.status = "Failed"
            payment.save(update_fields=["status"])
            return Response({"error": "Failed to create payment order"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        payment.razorpay_order_id = order.get("id")
        payment.save(update_fields=["razorpay_order_id"])

        logger.info("Razorpay order %s created for Payment %s", order.get("id"), payment.id)

        return Response({
            "registration_token": str(payment.registration_token),
            "order_id": order.get("id"),
            "amount": str(payment.amount),
            "currency": "INR",
            "razorpay_key": settings.RAZORPAY_KEY_ID,
        }, status=status.HTTP_201_CREATED)


class RazorpayVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RazorpayVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = Payment.objects.get(razorpay_order_id=data["razorpay_order_id"], status="Pending")
        except Payment.DoesNotExist:
            return Response({"error": "Payment not found or already processed"}, status=404)

        # Verify signature (unless test mode)
        verification_ok = False
        if getattr(settings, "RAZORPAY_TEST_MODE", True):
            verification_ok = True
        else:
            try:
                razorpay_client.utility.verify_payment_signature({
                    "razorpay_order_id": data["razorpay_order_id"],
                    "razorpay_payment_id": data["razorpay_payment_id"],
                    "razorpay_signature": data["razorpay_signature"],
                })
                verification_ok = True
            except Exception as e:
                logger.error("Razorpay signature verification failed for Payment %s: %s", payment.id, e)
                verification_ok = False

        if not verification_ok:
            payment.status = "Failed"
            payment.save(update_fields=["status"])
            return Response({"error": "Signature verification failed"}, status=400)

        # Mark verified and persist razorpay ids atomically
        with transaction.atomic():
            payment.razorpay_payment_id = data["razorpay_payment_id"]
            payment.razorpay_signature = data["razorpay_signature"]
            payment.status = "Verified"
            payment.save(update_fields=["razorpay_payment_id", "razorpay_signature", "status"])

        logger.info("Payment %s verified (order %s)", payment.id, data["razorpay_order_id"])

        # Create user from registration data
        reg_data = payment.get_registration_data()
        try:
            user = CustomUser.objects.create_user(
                user_id=generate_next_userid(),
                email=reg_data["email"],
                password=reg_data["password"],
                first_name=reg_data["first_name"],
                last_name=reg_data["last_name"],
                mobile=reg_data["mobile"],
                whatsapp_number=reg_data.get("whatsapp_number"),
                pincode=reg_data["pincode"],
                payment_type=reg_data["payment_type"],
                upi_number=reg_data.get("upi_number"),
                sponsor_id=reg_data["sponsor_id"],
                placement_id=reg_data.get("placement_id"),
                is_active=True,
            )
        except Exception as e:
            logger.exception("Failed to create user for Payment %s: %s", payment.id, e)
            # Consider rolling back or marking payment failed in extreme cases
            return Response({"error": "Failed to create user after payment verification"}, status=500)

        payment.user = user
        payment.save(update_fields=["user"])

        safe_send_mail(
            subject="Your MLM User ID",
            message=f"Hello {user.first_name},\n\nYour payment is verified. Your User ID is: {user.user_id}",
            recipient_list=[user.email],
        )

        return Response({
            "message": "Payment verified successfully",
            "user_id": user.user_id,
            "placement_id": user.placement_id,
        }, status=200)

class UploadReceiptView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

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
            user, created = CustomUser.objects.get_or_create(
                email=reg_data["email"],
                defaults={
                    "user_id": generate_next_userid(),
                    "password": reg_data.get("password") or "",
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
                if reg_data.get("password"):
                    user.set_password(reg_data["password"])
                user.is_active = True
                user.save()

            payment.user = user
            payment.save()

            if created:
                safe_send_mail(
                    subject="Your MLM User ID",
                    message=f"Hello {user.user_id},\n\nYour payment has been verified. Your User ID is: {user.user_id}",
                    recipient_list=[user.email],
                )
            return Response({"message": "Payment verified", "user_id": user.user_id})

        if payment.user and not payment.user.is_active:
            payment.user.is_active = True
            payment.user.save(update_fields=["is_active"])

        safe_send_mail(
            subject="Your MLM User ID",
            message=f"Hello {payment.user.user_id},\n\nYour payment has been verified. Your User ID is: {payment.user.user_id}",
            recipient_list=[payment.user.email],
        )

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

        # Log the reset link for debugging in Render logs
        logger.info(f"🔑 Password reset link for {user.email} ({user.user_id}): {reset_link}")

        safe_send_mail(
            subject="Reset Your Password",
            message=f"Click this link to reset your password:\n{reset_link}",
            recipient_list=[user.email],
        )
        return Response({
            "message": f"Password reset link sent to {user.user_id}'s email",
            "reset_link": reset_link  # Also include in API response
        })

        
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # Accept token from either query params or request body
        token = request.query_params.get('token') or request.data.get('token')
        if not token:
            return Response({"error": "Token is required"}, status=400)

        # Pass token into serializer context
        serializer = ResetPasswordSerializer(data=request.data, context={"token": token})
        serializer.is_valid(raise_exception=True)
        reset_token = serializer.validated_data['reset_token']
        user = reset_token.user

        # Update password
        user.set_password(serializer.validated_data['new_password'])
        user.save()

        # Mark token as used
        reset_token.is_used = True
        reset_token.save()

        safe_send_mail(
            subject="Password Reset Successful",
            message="Your password has been reset. You can now login using your new password.",
            recipient_list=[user.email],
        )

        return Response({"message": f"Password for {user.user_id} reset successfully."}, status=200)
        
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
        return apply_search_and_filters(
            CustomUser.objects.select_related("profile").all(),
            request
        )

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset(request)

        # Counts (before pagination)
        total_downline = queryset.count()
        active_count = queryset.filter(is_active=True).count()
        blocked_count = queryset.filter(is_active=False).count()

        # Export handling
        export_format = request.query_params.get("export")
        if export_format == "csv":
            return export_users_csv(queryset, filename="network_users.csv")
        if export_format == "pdf":
            return export_users_pdf(queryset, filename="network_users.pdf", title="Network Users Report")

        # Pagination
        paginator = PageNumberPagination()
        paginator.page_size = int(request.query_params.get("page_size", 10))
        page = paginator.paginate_queryset(queryset, request)

        serializer = AdminNetworkUserSerializer(page, many=True, context={"request": request})

        # ✅ Custom paginated response with counts
        return Response({
            "counts": {
                "total_downline": total_downline,
                "active_count": active_count,
                "blocked_count": blocked_count,
            },
            "pagination": {
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.page.paginator.per_page,
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
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
