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
    ChildRegistrationSerializer
    # VerifyOTPSerializer,
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
# from users.utils import generate_next_placementid
# from users.utils import assign_placement_id
from django.core.mail import send_mail
from django.core.mail import get_connection, EmailMultiAlternatives
import logging, socket
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.contrib.auth.hashers import make_password

from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from rest_framework import generics, status








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

# ----------------------------- Universal Safe Mail Sender (Brevo API) -----------------------------
def safe_send_mail(subject, message, recipient_list, from_email=None, otp=None, html_message=None):
    """
    Sends email using Brevo (Sendinblue) transactional API via Anymail config.
    Uses HTTPS (port 443) — works perfectly on Render.
    """
    from_email = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@winnersclubx.com")
    api_key = getattr(settings, "ANYMAIL", {}).get("SENDINBLUE_API_KEY")

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = api_key
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_list[0]}],
        sender={"email": from_email, "name": "Winners Club"},
        subject=subject,
        html_content=html_message or f"<p>{message}</p>",
        text_content=message,
    )

    try:
        response = api_instance.send_transac_email(send_smtp_email)
        logger.info(f"✅ Brevo email sent to {recipient_list}: {subject}")
    except ApiException as e:
        logger.exception(f"❌ Brevo API failed for {recipient_list}: {e}")

    if otp:
        logger.warning(f"🔐 OTP for {recipient_list}: {otp}")

def generate_next_userid():
    while True:
        random_part = "".join(random.choices(string.digits, k=6))
        user_id = f"WC{random_part}"
        if not CustomUser.objects.filter(user_id=user_id).exists():
            return user_id

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)

        # sanitize registration data before storing in Payment (don't store raw passwords)
        sanitized = {k: v for k, v in validated.items() if k not in ("password", "confirm_password")}

        amount = validated.get("amount", 100)

        try:
            with transaction.atomic():
                payment = Payment.objects.create(amount=amount)
                # store sanitized registration data in Payment (no raw password)
                payment.set_registration_data(sanitized)

                # create a separate RegistrationRequest that stores hashed password as required by model
                reg_req = RegistrationRequest.objects.create(
                    token=payment.registration_token,
                    sponsor_id=validated.get("sponsor_id") or None,
                    placement_id=validated.get("placement_id") or None,
                    first_name=validated.get("first_name"),
                    last_name=validated.get("last_name"),
                    email=validated.get("email"),
                    mobile=validated.get("mobile"),
                    whatsapp_number=validated.get("whatsapp_number"),
                    pincode=validated.get("pincode"),
                    payment_type=validated.get("payment_type"),
                    upi_number=validated.get("upi_number"),
                    password=make_password(validated.get("password")),
                    amount=int(amount) if isinstance(amount, (int,)) else int(float(amount)),
                    is_completed=False
                )

        except Exception as e:
            # attempt cleanup
            try:
                payment.delete()
            except Exception:
                pass
            return Response({"error": f"Unable to create registration: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "message": "Registration received. Please complete payment to activate your account.",
            "payment_id": payment.id,
            "registration_token": str(payment.registration_token),
            "amount": str(payment.amount),
            "payment_status": payment.status
        }, status=status.HTTP_201_CREATED)

# class VerifyOTPView(APIView):
#     permission_classes = [AllowAny]

#     def post(self, request, *args, **kwargs):
#         serializer = VerifyOTPSerializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
#         email = serializer.validated_data["email"].strip().lower()
#         otp = serializer.validated_data["otp"].strip()

#         try:
#             payment = Payment.objects.filter(status="Pending").latest("created_at")
#         except Payment.DoesNotExist:
#             return Response({"error": "No pending registration found."}, status=404)

#         reg_data = payment.get_registration_data()
#         if not reg_data or reg_data.get("email").lower() != email:
#             return Response({"error": "No matching registration found."}, status=404)

#         if reg_data.get("otp") != otp:
#             return Response({"error": "Invalid OTP."}, status=400)

#         expiry_minutes = int(getattr(settings, "OTP_EXPIRY_MINUTES", 10))
#         otp_time = datetime.fromisoformat(reg_data.get("otp_created_at"))
#         if otp_time + timedelta(minutes=expiry_minutes) < datetime.utcnow():
#             return Response({"error": "OTP expired. Please register again."}, status=400)

#         reg_data["otp"] = ""
#         payment.set_registration_data(reg_data)

#         return Response({
#             "message": "OTP verified successfully. Proceed to payment.",
#             "registration_token": str(payment.registration_token),
#             "amount": str(payment.amount),
#         }, status=200)
               
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

        # >>> CHANGED: Instead of assuming plaintext password is in reg_data,
        # fetch the corresponding RegistrationRequest which stores the hashed password.
        try:
            # Try to get the hashed password from RegistrationRequest
            reg_req = RegistrationRequest.objects.filter(token=payment.registration_token).first()
        except Exception:
            reg_req = None

        try:
            # If we found a RegistrationRequest, use it (password is already hashed)
            if reg_req:
                user = CustomUser(
                    user_id=generate_next_userid(),
                    email=reg_data.get("email"),
                    first_name=reg_data.get("first_name"),
                    last_name=reg_data.get("last_name"),
                    mobile=reg_data.get("mobile"),
                    whatsapp_number=reg_data.get("whatsapp_number"),
                    pincode=reg_data.get("pincode") or "",
                    payment_type=reg_data.get("payment_type") or "",
                    upi_number=reg_data.get("upi_number") or "",
                    sponsor_id=reg_data.get("sponsor_id"),
                    placement_id=reg_data.get("placement_id"),
                    is_active=True,
                )
                # assign hashed password directly so we DON'T double-hash
                if reg_req.password:
                    user.password = reg_req.password
                else:
                    # fallback: if somehow the request didn't store a hashed password but reg_data has raw
                    if reg_data.get("password"):
                        user.set_password(reg_data.get("password"))
                    else:
                        user.set_unusable_password()
                user.save()
            else:
                # No RegistrationRequest found — fallback to older approach,
                # but guard against missing raw password.
                raw_pw = reg_data.get("password")
                user = CustomUser.objects.create_user(
                    user_id=generate_next_userid(),
                    email=reg_data.get("email"),
                    password=raw_pw,
                    first_name=reg_data.get("first_name"),
                    last_name=reg_data.get("last_name"),
                    mobile=reg_data.get("mobile"),
                    whatsapp_number=reg_data.get("whatsapp_number"),
                    pincode=reg_data.get("pincode") or "",
                    payment_type=reg_data.get("payment_type") or "",
                    upi_number=reg_data.get("upi_number") or "",
                    sponsor_id=reg_data.get("sponsor_id"),
                    placement_id=reg_data.get("placement_id"),
                    is_active=True,
                )
        except Exception as e:
            logger.exception("Failed to create user for Payment %s: %s", payment.id, e)
            # Consider rolling back or marking payment failed in extreme cases
            return Response({"error": "Failed to create user after payment verification"}, status=500)

        payment.user = user
        payment.save(update_fields=["user"])

        # ✅ Send confirmation via Brevo
        safe_send_mail(
            subject="Your MLM User ID",
            message=f"Hello {user.first_name},\nYour payment is verified. Your User ID is: {user.user_id}",
            recipient_list=[user.email],
            html_message=f"<p>Hello <strong>{user.first_name}</strong>,</p><p>Your payment is verified. Your User ID is: <strong>{user.user_id}</strong>.</p>"
        )

        return Response({
            "message": "Payment verified successfully",
            "user_id": user.user_id,
            # "placement_id": user.placement_id,
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
        if status_filter in ["Pending", "Verified", "Failed", "Declined"]:
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

    logger = logging.getLogger(__name__)

    def post(self, request, payment_id=None):
        logger.info("AdminVerifyPaymentView called for payment_id=%s by user=%s, data=%s",
                    payment_id, getattr(request.user, 'id', None), request.data)
        try:
            payment = Payment.objects.get(id=payment_id)
        except Payment.DoesNotExist:
            return Response({"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("status")
        if new_status not in ["Verified", "Declined", "Failed", "Pending"]:
            return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

        # If admin is verifying, create/link user similar to RazorpayVerifyView
        if new_status == "Verified":
            try:
                with transaction.atomic():
                    # persist status first
                    payment.status = "Verified"
                    payment.save(update_fields=["status"])

                    # --- Replacement: Always create a new user on admin verification by default ---
                    reg_data = payment.get_registration_data() or {}
                    email = reg_data.get("email")

                    # Allow admin to explicitly link to an existing user by passing ?link_existing=true (optional)
                    link_existing = str(request.query_params.get("link_existing", "")).lower() == "true" \
                                    or str(request.data.get("link_existing", "")).lower() == "true"

                    if link_existing and email:
                        # preserve current behavior if admin explicitly wants to link to existing user
                        user = CustomUser.objects.filter(email=email).first()
                        if user:
                            user.is_active = True
                            user.save(update_fields=["is_active"])
                            payment.user = user
                            payment.save(update_fields=["user"])
                            RegistrationRequest.objects.filter(token=payment.registration_token).update(is_completed=True)

                            safe_send_mail(
                                subject="Your MLM User ID",
                                message=f"Hello {user.first_name},\nYour payment is verified. Your User ID is: {user.user_id}",
                                recipient_list=[user.email],
                                html_message=f"<p>Hello <strong>{user.first_name}</strong>,</p><p>Your payment is verified. Your User ID is: <strong>{user.user_id}</strong>.</p>",
                            )

                            return Response({
                                "message": "Payment verified, UserId is send to your email.",
                                "user_id": user.user_id
                            }, status=status.HTTP_200_OK)

                    # Otherwise: always create a new user from RegistrationRequest (if present) or from registration_data
                    reg_req = RegistrationRequest.objects.filter(token=payment.registration_token).first()

                    if reg_req:
                        # create user using reg_req (reg_req.password is already hashed by RegisterView)
                        user = CustomUser(
                            user_id=generate_next_userid(),
                            email=reg_data.get("email") or reg_req.email,
                            first_name=reg_req.first_name or reg_data.get("first_name"),
                            last_name=reg_req.last_name or reg_data.get("last_name"),
                            mobile=reg_req.mobile or reg_data.get("mobile"),
                            whatsapp_number=reg_req.whatsapp_number or reg_data.get("whatsapp_number"),
                            pincode=reg_req.pincode or reg_data.get("pincode") or "",
                            payment_type=reg_req.payment_type or reg_data.get("payment_type") or "",
                            upi_number=reg_req.upi_number or reg_data.get("upi_number") or "",
                            sponsor_id=reg_req.sponsor_id or reg_data.get("sponsor_id"),
                            placement_id=reg_req.placement_id or reg_data.get("placement_id"),
                            is_active=True,
                        )
                        # assign hashed password directly if stored on reg_req
                        if getattr(reg_req, "password", None):
                            user.password = reg_req.password
                        else:
                            # fallback to raw in registration_data (unlikely)
                            if reg_data.get("password"):
                                user.set_password(reg_data.get("password"))
                            else:
                                user.set_unusable_password()
                        user.save()
                        reg_req.is_completed = True
                        reg_req.save(update_fields=["is_completed"])
                    else:
                        # fallback: use registration_data to create user (rare case)
                        raw_pw = reg_data.get("password")
                        if not reg_data.get("email"):
                            # email required to create user: revert payment to Pending and error out
                            payment.status = "Pending"
                            payment.save(update_fields=["status"])
                            return Response({"error": "Registration data missing email; cannot create user."},
                                            status=status.HTTP_400_BAD_REQUEST)

                        user = CustomUser.objects.create_user(
                            user_id=generate_next_userid(),
                            email=reg_data.get("email"),
                            password=raw_pw,
                            first_name=reg_data.get("first_name"),
                            last_name=reg_data.get("last_name"),
                            mobile=reg_data.get("mobile"),
                            whatsapp_number=reg_data.get("whatsapp_number"),
                            pincode=reg_data.get("pincode") or "",
                            payment_type=reg_data.get("payment_type") or "",
                            upi_number=reg_data.get("upi_number") or "",
                            sponsor_id=reg_data.get("sponsor_id"),
                            placement_id=reg_data.get("placement_id"),
                            is_active=True,
                        )

                    # attach and notify
                    payment.user = user
                    payment.save(update_fields=["user"])
                    safe_send_mail(
                        subject="Your MLM User ID",
                        message=f"Hello {user.first_name},\nYour payment is verified. Your User ID is: {user.user_id}",
                        recipient_list=[user.email],
                        html_message=f"<p>Hello <strong>{user.first_name}</strong>,</p><p>Your payment is verified. Your User ID is: <strong>{user.user_id}</strong>.</p>",
                    )

                    return Response({
                        "message": "Payment verified, UserId is send to your email.",
                        "user_id": user.user_id
                    }, status=status.HTTP_200_OK)


            except Exception as exc:
                logger.exception("Unexpected error in admin verify payment: %s", exc)
                # revert to pending so admin can retry
                payment.status = "Pending"
                payment.save(update_fields=["status"])
                return Response({"error": "Unexpected error verifying payment"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # For non-Verified statuses just update status
        payment.status = new_status
        payment.save(update_fields=["status"])
        return Response({"message": f"Payment status updated to {new_status}"}, status=status.HTTP_200_OK)

class AdminAccountAPIView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.AllowAny()]
        return [IsProjectAdmin()]

    def get(self, request):
        details = AdminAccountDetails.objects.last()
        if not details:
            return Response({}, status=200)
        return Response(AdminAccountSerializer(details).data, status=200)

    def post(self, request):
        details = AdminAccountDetails.objects.last()
        serializer = AdminAccountSerializer(instance=details, data=request.data, partial=True)
        if serializer.is_valid():
            obj = serializer.save()
            return Response(AdminAccountSerializer(obj).data, status=200)
        return Response(serializer.errors, status=400)
    
    def delete(self, request):
        details = AdminAccountDetails.objects.last()
        if not details:
            return Response({"error": "No account details found."}, status=404)
        details.delete()
        return Response({"message": "Admin account details deleted successfully."}, status=200)

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
            message=f"Click this link to reset your password: {reset_link}",
            recipient_list=[user.email],
            html_message=f"<p>Click this link to reset your password: {reset_link}</p>"
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
            html_message=f"<p><strong>Your password has been reset. You can now login using your new password.</strong>.</p>"
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

def compute_user_levels():
    """
    Precompute levels for all users (based on sponsor chain).
    Returns a dict {user_id: level}.
    """
    users = CustomUser.objects.values("id", "user_id", "sponsor_id")
    users_map = {u["user_id"]: u for u in users}
    levels = {}

    def get_level(uid, visited=None):
        if uid in levels:
            return levels[uid]
        if visited is None:
            visited = set()
        if uid in visited:
            return None  # cycle
        visited.add(uid)
        user = users_map.get(uid)
        if not user or not user["sponsor_id"]:
            levels[uid] = 0
            return 0
        sponsor_uid = user["sponsor_id"]
        sponsor_level = get_level(sponsor_uid, visited)
        if sponsor_level is None:
            return None
        levels[uid] = sponsor_level + 1
        return levels[uid]

    for u in users:
        get_level(u["user_id"])
    return levels

def apply_search_and_filters(queryset, request,user_levels=None):
    """Reusable function for search, status, date filters"""
    if user_levels is None:
        user_levels = compute_user_levels()

    params = getattr(request, "query_params", {}) or {}
    data = getattr(request, "data", {}) or {}

    def get_param(key):
        return params.get(key) or data.get(key)
    
    # --- Search filter ---
    search = (get_param("search") or "").strip()
    if search:
        parts = search.split()
        if len(parts) >= 2:
            queryset = queryset.filter(
                Q(user_id__icontains=search) |
                (Q(first_name__icontains=parts[0]) &
                 Q(last_name__icontains=" ".join(parts[1:])))
            )
        else:
            queryset = queryset.filter(
                Q(user_id__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )
    # --- Status filter ---
    status_filter = (get_param("status") or "").lower()
    if status_filter == "active":
        queryset = queryset.filter(is_active=True)
    elif status_filter == "blocked":
        queryset = queryset.filter(is_active=False)

    # --- Date filters ---
    date_format = "%Y-%m-%d"
    start_date = get_param("start_date")
    end_date = get_param("end_date")

    if start_date:
        try:
            start = datetime.strptime(start_date, date_format)
            queryset = queryset.filter(date_of_joining__gte=start)
        except (ValueError, TypeError):
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, date_format)
            queryset = queryset.filter(date_of_joining__lte=end)
        except (ValueError, TypeError):
            pass

    # --- Level filter ---
    level_filter = get_param("level")
    if level_filter is not None:
        try:
            target_level = int(level_filter)
            valid_ids = [uid for uid, lvl in user_levels.items() if lvl == target_level]
            queryset = queryset.filter(user_id__in=valid_ids)
        except (ValueError, TypeError):
            pass

    
    sort_by = get_param("sort_by") or "date_of_joining"  # default sort field
    sort_order = (get_param("sort_order") or "desc").lower()

    # Only allow sorting by safe fields
    allowed_fields = {
        "first_name": "first_name",
        "last_name": "last_name",
        "email": "email",
        "user_id": "user_id",
        "date_of_joining": "date_of_joining",
    }

    if sort_by in allowed_fields:
        sort_field = allowed_fields[sort_by]
        if sort_order == "desc":
            sort_field = f"-{sort_field}"
        queryset = queryset.order_by(sort_field)

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
        user_levels = compute_user_levels()
        queryset = apply_search_and_filters(queryset, request, user_levels=user_levels)
        export_format = self.get_export_format(request)

        if export_format == "csv":
            return export_users_csv(queryset, filename="users.csv", user_levels=user_levels)
        elif export_format == "pdf":
            return export_users_pdf(queryset, filename="users.pdf", user_levels=user_levels)

        # Pagination
        paginator = AdminUserPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = AdminUserListSerializer(
            page, many=True, context={"request": request, "level_map": user_levels}
        )
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
        user_levels = compute_user_levels()

        # Filter by start_date / end_date
        start_date = request.query_params.get("start_date") or request.data.get("start_date")
        end_date = request.query_params.get("end_date") or request.data.get("end_date")
        if start_date:
            users = users.filter(date_of_joining__gte=start_date)
        if end_date:
            users = users.filter(date_of_joining__lte=end_date)

        # Apply search / status / level filters    
        users = apply_search_and_filters(users, request, user_levels=user_levels)

        # Export if requested
        if export_format == "csv":
            return export_users_csv(users, filename="users.csv", user_levels=user_levels)
        elif export_format == "pdf":
            return export_users_pdf(users, filename="users.pdf", user_levels=user_levels)

        # Paginate
        paginator = AdminUserPagination()
        page = paginator.paginate_queryset(users, request)
        serializer = AdminUserListSerializer(
            page, many=True, context={"level_map": user_levels}
        )

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
    
    def delete(self, request, user_id):
        """Project admin can permanently delete a user — never another admin."""
        try:
            user = CustomUser.objects.select_related('profile').get(user_id=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Prevent admin from deleting themselves
        if request.user and getattr(request.user, 'user_id', None) == user.user_id:
            return Response({"error": "You cannot delete your own account via this endpoint."}, status=400)

        # --- Stronger protection against deleting admin users ---
        # Block deletion if user has *any* admin privileges
        admin_flags = [
            getattr(user, "is_superuser", False),
            getattr(user, "is_staff", False),
            getattr(user, "is_admin_user", False),
            getattr(user, "is_project_admin", False),
            getattr(user, "role", "").lower() in ["admin", "superadmin", "projectadmin"],
            getattr(user, "user_type", "").lower() in ["admin", "superadmin"],
        ]
        if any(admin_flags):
            return Response(
                {"error": "Deletion blocked: admin/superuser accounts cannot be deleted via this endpoint."},
                status=403,
            )

        try:
            with transaction.atomic():
                # Delete profile image if present
                profile = getattr(user, 'profile', None)
                if profile and getattr(profile, 'profile_image', None):
                    try:
                        profile.profile_image.delete(save=False)
                    except Exception:
                        pass

                # Delete KYC images if present
                kyc = getattr(user, 'kyc', None)
                if kyc:
                    for field in ['pan_image', 'id_card_image']:
                        image = getattr(kyc, field, None)
                        if image:
                            try:
                                image.delete(save=False)
                            except Exception:
                                pass

                # Delete payment receipts if any
                payments = getattr(user, 'payments', None)
                if payments is not None:
                    try:
                        for pay in payments.all():
                            if getattr(pay, 'receipt', None):
                                pay.receipt.delete(save=False)
                    except Exception:
                        pass

                # Finally delete user
                user.delete()

        except Exception as exc:
            return Response({"error": f"Failed to delete user: {str(exc)}"}, status=500)

        return Response({"message": f"User {user_id} deleted successfully"}, status=200)

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
            html_message=f"<p>Your password has been reset by the admin.</strong>,</p><p>Your new password is: {new_password}.</p>"
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
        export_format = request.query_params.get("export", "").lower()

        # Precompute levels once
        user_levels = compute_user_levels()

        # ✅ If export requested, skip pagination and return immediately
        # if export_format in ["csv", "pdf"]:
            # for user in queryset:
            #     user.level = user_levels.get(user.user_id, "")

        if export_format == "csv":
            return export_users_csv(queryset, filename="network_users.csv", user_levels=user_levels)
        elif export_format == "pdf":
            return export_users_pdf(queryset, filename="network_users.pdf", title="Network Users Report", user_levels=user_levels)

        # Counts (before pagination)
        total_downline = queryset.count()
        active_count = queryset.filter(is_active=True).count()
        blocked_count = queryset.filter(is_active=False).count()

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

class ChildPagination(PageNumberPagination):
    page_size = 12
    page_query_param = 'page'
    page_size_query_param = 'page_size'
    max_page_size = 50





class ChildRegistrationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChildRegistrationSerializer(
            data=request.data, 
            context={'request': request}
        )
        if serializer.is_valid():
            child = serializer.save()
            return Response({
                "message": "Child user created successfully",
                "user_id": child.user_id, 
                "child_password": request.data.get("password"),      
                "parent_user_id": request.user.user_id,
                
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChildListView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = ChildPagination
    queryset = CustomUser.objects.all()

    def get(self, request):
        user = request.user
        query_params = request.query_params

        # Base queryset
        if user.is_staff:
            children = CustomUser.objects.filter(parent__isnull=False)
        else:
            children = CustomUser.objects.filter(parent=user)

        # Filters (admin only)
        if user.is_staff:
            parent_user_id = query_params.get("parent_user_id")
            child_user_id = query_params.get("user_id")
            email = query_params.get("email")
            mobile = query_params.get("mobile")
            date_joined = query_params.get("date_joined")  # format: YYYY-MM-DD

            if parent_user_id:
                children = children.filter(parent__user_id=parent_user_id)
            if child_user_id:
                children = children.filter(user_id=child_user_id)
            if email:
                children = children.filter(email__icontains=email)
            if mobile:
                children = children.filter(mobile__icontains=mobile)
            if date_joined:
                children = children.filter(date_of_joining__date=date_joined)

        # Check for PDF export
        export_pdf = query_params.get("export_pdf", "false").lower() == "true"
        if export_pdf and user.is_staff:
            return self.export_pdf(children)

        # Paginate queryset
        page = self.paginate_queryset(children)
        if page is not None:
            data = self.serialize_children(page, user)
            return self.get_paginated_response(data)

        # If pagination not applied
        data = self.serialize_children(children, user)
        return Response(data, status=status.HTTP_200_OK)

    def serialize_children(self, queryset, user):
        """Helper function to build response data"""
        data = []
        for c in queryset:
            if user.is_staff:
                data.append({
                    "user_id": c.user_id,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "email": c.email,
                    "mobile": c.mobile,
                    "whatsapp_number": c.whatsapp_number,
                    "role": c.role,
                    "parent_user_id": c.parent.user_id if c.parent else None,
                    "date_of_joining": c.date_of_joining,
                    "is_active": c.is_active,
                })
            else:
                data.append({
                    "user_id": c.user_id,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "email": c.email,
                    "mobile": c.mobile,
                })
        return data

    def export_pdf(self, queryset):
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        y = height - 50

        p.setFont("Helvetica-Bold", 14)
        p.drawString(200, y, "Child User List")
        y -= 30
        p.setFont("Helvetica", 10)

        for c in queryset:
            line = (
                f"User ID: {c.user_id}, Name: {c.first_name} {c.last_name}, "
                f"Email: {c.email}, Mobile: {c.mobile}, "
                f"Parent ID: {c.parent.user_id if c.parent else 'N/A'}, "
                f"Joined: {c.date_of_joining.strftime('%Y-%m-%d') if c.date_of_joining else 'N/A'}, "
                f"Role: {c.role}, Active: {c.is_active}"
            )
            p.drawString(50, y, line)
            y -= 20
            if y < 50:
                p.showPage()
                y = height - 50

        p.save()
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename="child_users.pdf")

class SwitchToChildView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, child_user_id):
        try:
            child = CustomUser.objects.get(user_id=child_user_id, parent=request.user)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "Child not found or not owned by this parent."},
                status=status.HTTP_404_NOT_FOUND
            )

        refresh = RefreshToken.for_user(child)
        refresh["parent_user_id"] = request.user.user_id

        return Response({
            "message": f"Switched to child account {child.user_id}",
            "child_user_id": child.user_id,
            "parent_user_id": request.user.user_id,
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        })

class SwitchBackToParentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check  session has parent_user_id from token
        parent_user_id = getattr(request.auth, "payload", {}).get("parent_user_id") \
            if request.auth else None

        if not parent_user_id:
            return Response(
                {"error": "Cannot switch back. This session was not initiated by a parent."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            parent = CustomUser.objects.get(user_id=parent_user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "Parent user not found."}, status=status.HTTP_404_NOT_FOUND)

        refresh = RefreshToken.for_user(parent)
        return Response({
            "message": f"Switched back to parent account {parent.user_id}",
            "parent_user_id": parent.user_id,
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }, status=status.HTTP_200_OK)
