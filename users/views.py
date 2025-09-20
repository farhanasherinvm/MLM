import string, random, razorpay, csv
from django.conf import settings
from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics, filters
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from .models import *
from .serializers import *
from .permissions import IsProjectAdmin
from django.utils.crypto import get_random_string
from .utils import validate_sponsor
from django.db.models import Q
from io import BytesIO
from reportlab.pdfgen import canvas
from django.http import HttpResponse, FileResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from rest_framework.permissions import IsAdminUser
from profiles.models import Profile

# import admin serializer from profiles
from profiles.serializers import AdminUserListSerializer, AdminUserDetailSerializer, AdminNetworkUserSerializer

def generate_next_userid():
    while True:
        random_part = "".join(random.choices(string.digits, k=6))
        user_id = f"WS{random_part}"
        if not CustomUser.objects.filter(user_id=user_id).exists():
            return user_id



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
        serializer = RazorpayVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        data = serializer.validated_data

        try:
            payment = Payment.objects.get(
                razorpay_order_id=data["razorpay_order_id"],
                status="Pending"
            )
        except Payment.DoesNotExist:
            return Response({"error": "Payment not found or already processed"}, status=404)

        # 🔹 Mock verification for Postman / dev mode
        if getattr(settings, "RAZORPAY_TEST_MODE", True):
            verification_ok = True
        else:
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            try:
                client.utility.verify_payment_signature({
                    "razorpay_order_id": data["razorpay_order_id"],
                    "razorpay_payment_id": data["razorpay_payment_id"],
                    "razorpay_signature": data["razorpay_signature"],
                })
                verification_ok = True
            except:
                verification_ok = False

        if not verification_ok:
            payment.status = "Failed"
            payment.save()
            return Response({"error": "Signature verification failed"}, status=400)

        # ✅ Get registration data from payment
        reg_data = payment.get_registration_data()

        # Validate sponsor before user creation
        sponsor_id = reg_data.get("sponsor_id") or reg_data.get("sponsor_id")
        if sponsor_id:
            validate_sponsor(sponsor_id)

        # Check if user with this email already exists
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

        # Ensure password is set correctly for newly created user
        if created:
            user.set_password(reg_data["password"])
            user.save()

        # Update payment record
        payment.user = user
        payment.status = "Verified"
        payment.razorpay_payment_id = data["razorpay_payment_id"]
        payment.razorpay_signature = data["razorpay_signature"]
        payment.save()

        # Send email only if newly created
        if created:
            send_mail(
                subject="Your MLM UserID",
                message=f"Your UserID is {user.user_id}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )

        return Response({
            "message": "Payment verified and user created" if created else "Payment verified, user already exists",
            "user_id": user.user_id
        })
   
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
    permission_classes = [AllowAny]
    def post(self, request, payment_id, *args, **kwargs):
        try:
            payment = Payment.objects.get(id=payment_id)
        except Payment.DoesNotExist:
            return Response({"error": "Payment not found"}, status=404)

        status_choice = request.data.get("status")
        if status_choice not in ["Verified", "Failed"]:
            return Response({"error": "Invalid status"}, status=400)

        payment.status = status_choice
        payment.save()

        if status_choice == "Verified" and not payment.user:
            reg_data = payment.get_registration_data()
            sponsor_id = reg_data.get("sponsor_id")
            if sponsor_id and not validate_sponsor(sponsor_id):
                return Response({"error": "Sponsor already has 2 referrals. Cannot assign this sponsor."}, status=400)


            # Check if a user with this email already exists
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

            # Send email only if newly created
            if created:
                send_mail(
                    subject="Your MLM User ID",
                    message=f"Hello {user.user_id},\n\nYour payment has been verified. Your User ID is: {user.user_id}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            return Response({
                "message": "Payment verified and user created" if created else "Payment verified, user already exists",
                "user_id": user.user_id
            })

        return Response({"message": f"Payment {status_choice} successfully"})

    
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

        send_mail(
            subject="Reset Your Password",
            message=f"Click this link to reset your password:\n{reset_link}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
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

        send_mail(
            subject="Password Reset Successful",
            message=f"Your password has been reset. You can now login using your new password.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
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


class AdminListUsersView(APIView):
    permission_classes = [IsProjectAdmin]

    def get(self, request):
        search_query = request.query_params.get("search", "")
        if search_query:
            users = CustomUser.objects.filter(
                Q(username__icontains=search_query) |
                Q(user_id__icontains=search_query)
            )
        else:
            users = CustomUser.objects.all()

        serializer = CustomUserSerializer(users, many=True)
        return Response(serializer.data)


class AdminUserListView(APIView):
    """
    Returns a compact list for admins:
      - username
      - user_id
      - level
      - profile_image
    """
    permission_classes = [IsProjectAdmin]

    def get(self, request):
        search_query = request.query_params.get("search", "")
        if search_query:
            users = CustomUser.objects.filter(
                Q(username__icontains=search_query) |
                Q(user_id__icontains=search_query)
            ).select_related("profile")
        else:
            users = CustomUser.objects.all().select_related("profile")

        serializer = AdminUserListSerializer(users, many=True, context={"request": request})
        return Response(serializer.data, status=200)


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
        send_mail(
            subject="Your Password Has Been Reset",
            message=f"Hello {user.first_name},\n\nYour password has been reset by the admin. Your new password is: {new_password}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )

        return Response({"message": f"Password reset successfully for {user.user_id}"})

   
class AdminExportUsersCSVView(APIView):
    permission_classes = [IsProjectAdmin]

    def get(self, request):
        users = CustomUser.objects.all().select_related("profile")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="users.csv"'
        writer = csv.writer(response)

        # Header
        writer.writerow(["Name", "User ID", "Level", "Profile Image", ])

        for user in users:
            profile_img = ""
            if hasattr(user, "profile") and user.profile.profile_image:
                profile_img = user.profile.profile_image.url

            full_name = f"{user.first_name} {user.last_name}".strip()
            writer.writerow([full_name, user.user_id, user.level, profile_img])

        return response


class AdminExportUsersPDFView(APIView):
    permission_classes = [IsProjectAdmin]

    def get(self, request, *args, **kwargs):
        users = CustomUser.objects.all().select_related("profile")
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="users.pdf"'

        p = canvas.Canvas(response, pagesize=A4)
        width, height = A4
        y = height - 50

        # Column positions
        col_name = 50
        col_user_id = 200
        col_level = 300
        col_email = 400
        col_profile = 550

        # Header
        p.setFont("Helvetica-Bold", 14)
        p.drawString(col_name, y, "Name")
        p.drawString(col_user_id, y, "User ID")
        p.drawString(col_level, y, "Level")
        p.drawString(col_email, y, "Email")
        p.drawString(col_profile, y, "Profile Image")
        y -= 20
        p.line(50, y, width - 50, y)  # horizontal line
        y -= 20

        # User data
        p.setFont("Helvetica", 12)
        for user in users:
            if y < 50:
                p.showPage()
                y = height - 50
                p.setFont("Helvetica-Bold", 14)
                p.drawString(col_name, y, "Name")
                p.drawString(col_user_id, y, "User ID")
                p.drawString(col_level, y, "Level")
                p.drawString(col_email, y, "Email")
                p.drawString(col_profile, y, "Profile Image")
                y -= 20
                p.line(50, y, width - 50, y)
                y -= 20
                p.setFont("Helvetica", 12)

            profile_img = (
                user.profile.profile_image.url
                if hasattr(user, "profile") and user.profile.profile_image
                else "No Image"
            )

            display_name = f"{user.first_name} {user.last_name}"
            p.drawString(col_name, y, display_name)
            p.drawString(col_user_id, y, user.user_id)
            p.drawString(col_level, y, str(user.level))
            p.drawString(col_email, y, user.email)
            p.drawString(col_profile, y, profile_img[:30])  # truncate long URLs
            y -= 20

        p.showPage()
        p.save()
        return response
    
    
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
    permission_classes = [IsAdminUser]

    def get_queryset(self, request):
        """Apply search and filtering logic while preserving QuerySet methods."""
        queryset = CustomUser.objects.all()

        # 🔎 Search by first_name, last_name, or user_id
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(user_id__icontains=search)
            )

        # 🔎 Filter by active status
        status_filter = request.query_params.get("status")
        if status_filter == "active":
            queryset = queryset.filter(is_active=True)
        elif status_filter == "blocked":
            queryset = queryset.filter(is_active=False)

        # Keep queryset as Django QuerySet for counts
        return queryset

    def filter_by_level(self, queryset, level_filter):
        """Filter a QuerySet by computed user.level without breaking QuerySet methods."""
        if not level_filter:
            return queryset
        try:
            level_filter = int(level_filter)
        except ValueError:
            return queryset

        # Evaluate level property after queryset evaluation
        return [user for user in queryset if user.level == level_filter]

    def get(self, request, *args, **kwargs):
        export_format = request.query_params.get("export")
        queryset = self.get_queryset(request)

        # Counts
        total_downline = queryset.count()
        active_count = queryset.filter(is_active=True).count()
        blocked_count = queryset.filter(is_active=False).count()

        # Filter by level after counts
        level_filter = request.query_params.get("level")
        filtered_users = self.filter_by_level(queryset, level_filter)

        # CSV Export
        if export_format == "csv":
            return self.export_csv(filtered_users)

        # PDF Export
        if export_format == "pdf":
            return self.export_pdf(filtered_users)

        # Default → JSON
        serializer = AdminNetworkUserSerializer(filtered_users, many=True, context={"request": request})
        return Response({
            "counts": {
                "total_downline": total_downline,
                "active_count": active_count,
                "blocked_count": blocked_count,
            },
            "users": serializer.data
        })

    def export_csv(self, queryset):
        """Export users as CSV."""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="network_users.csv"'

        writer = csv.writer(response)
        writer.writerow(["Username", "Sponsor", "Level", "Join Date", "Status"])

        for user in queryset:
            sponsor_display = "N/A"
            if user.sponsor_id:
                try:
                    sponsor = CustomUser.objects.get(user_id=user.sponsor_id)
                    sponsor_display = f"{sponsor.user_id} / {sponsor.first_name} {sponsor.last_name}".strip()
                except CustomUser.DoesNotExist:
                    sponsor_display = "N/A"

            writer.writerow([
                f"{user.first_name} {user.last_name}".strip() or user.user_id,
                sponsor_display,
                user.level,
                user.date_of_joining.strftime("%Y-%m-%d") if user.date_of_joining else "",
                "Active" if user.is_active else "Blocked",
            ])

        return response

    def export_pdf(self, queryset):
        """Export users as nicely formatted PDF table."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)

        elements = []
        styles = getSampleStyleSheet()
        title = Paragraph("Network Users Report", styles["Title"])
        elements.append(title)

        data = [["User ID", "Username", "Level", "Sponsor", "Join Date", "Status"]]
        for user in queryset:
            sponsor_name = None
            if user.sponsor_id:
                try:
                    sponsor = CustomUser.objects.get(user_id=user.sponsor_id)
                    sponsor_name = f"{sponsor.first_name} {sponsor.last_name}".strip()
                except CustomUser.DoesNotExist:
                    sponsor_name = "N/A"

            data.append([
                user.user_id,
                f"{user.first_name} {user.last_name}".strip(),
                user.level,
                sponsor_name,
                user.date_of_joining.strftime("%Y-%m-%d") if user.date_of_joining else "",
                "Active" if user.is_active else "Blocked",
            ])

        table = Table(data, colWidths=[70, 100, 40, 100, 70, 60])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))

        elements.append(table)
        doc.build(elements)

        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="network_users.pdf"'
        response.write(pdf)
        return response