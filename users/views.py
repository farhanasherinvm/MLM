from rest_framework import generics, status
from django.contrib.auth import authenticate
from django.http import JsonResponse
from rest_framework.response import Response
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import check_password
from django.conf import settings
import json
import secrets
from .models import CustomUser
from .serializers import UserRegistrationSerializer
from .utils import get_tokens_for_user
from django.shortcuts import render
from django.http import HttpResponse
from rest_framework import generics, permissions



class UserRegistrationView(generics.CreateAPIView):
    queryset = CustomUser.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny] 

    def perform_create(self, serializer):
        user = serializer.save()
        # Send User ID to email
        subject = "Welcome to MLM Platform"
        message = f"Hello {user.first_name},\n\nYour unique User ID is: {user.user_id}\nUse this ID to login."
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        return user
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = self.perform_create(serializer)  # returns user
        headers = self.get_success_headers(serializer.data)

        tokens = get_tokens_for_user(user)

        return Response({
            "status": "success",
            "message": "User registered successfully. User ID sent to email.",
            "user_id": user.user_id,
            "tokens": tokens
        }, status=status.HTTP_201_CREATED, headers=headers)

@csrf_exempt
def login_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_id = data.get("user_id")
            password = data.get("password")

            if not user_id or not password:
                return JsonResponse({"status": "error", "message": "UserId and Password required"}, status=400)

            try:
                user = CustomUser.objects.get(user_id=user_id)
            except CustomUser.DoesNotExist:
                return JsonResponse({"status": "error", "message": "Invalid UserId or Password"}, status=400)

            if check_password(password, user.password):
                tokens = get_tokens_for_user(user)
                return JsonResponse({
                    "status": "success",
                    "message": "Login successful",
                    "user": {
                        "user_id": user.user_id,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "email": user.email,
                        "mobile": user.mobile,
                    },
                    "tokens": tokens
                }, status=200)
            else:
                return JsonResponse({"status": "error", "message": "Invalid UserId or Password"}, status=400)

        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON format"}, status=400)

    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)

reset_tokens = {}

@csrf_exempt
def forgot_password(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_id = data.get("user_id")
            email = data.get("email")

            try:
                user = CustomUser.objects.get(user_id=user_id, email=email)
            except CustomUser.DoesNotExist:
                return JsonResponse({"status": "error", "message": "Invalid UserId or Email"}, status=400)

            # Generate reset token
            token = secrets.token_urlsafe(16)
            reset_tokens[user_id] = token  # store temporarily

            reset_link = f"http://127.0.0.1:8000/api/reset-password-link/?user_id={user_id}&token={token}"

            # Send Email
            subject = "Password Reset Request"
            message = f"Hello {user.first_name},\n\nClick the link below to reset your password:\n{reset_link}\n\nIf you didn’t request this, ignore this email."
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)

            return JsonResponse({"status": "success", "message": "Password reset link sent to email"}, status=200)

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)

@csrf_exempt
def reset_password_link(request):
    user_id = request.GET.get("user_id")
    token = request.GET.get("token")

    if request.method == "GET":
        # Check if token is valid
        if reset_tokens.get(user_id) != token:
            return HttpResponse("Invalid or expired token", status=400)

        # Render a simple HTML form
        return HttpResponse(f"""
            <html>
                <body>
                    <h2>Reset Password for User ID: {user_id}</h2>
                    <form method="POST">
                        <input type="hidden" name="user_id" value="{user_id}">
                        <input type="hidden" name="token" value="{token}">
                        <label>New Password:</label><br>
                        <input type="password" name="new_password"><br><br>
                        <label>Confirm Password:</label><br>
                        <input type="password" name="confirm_password"><br><br>
                        <input type="submit" value="Reset Password">
                    </form>
                </body>
            </html>
        """)

    elif request.method == "POST":
        new_password = request.POST.get("new_password")
        confirm_password = request.POST.get("confirm_password")

        if new_password != confirm_password:
            return HttpResponse("Passwords do not match", status=400)

        if reset_tokens.get(user_id) != token:
            return HttpResponse("Invalid or expired token", status=400)

        try:
            user = CustomUser.objects.get(user_id=user_id)
            user.set_password(new_password)
            user.save()

            # Clear token
            reset_tokens.pop(user_id, None)

            return HttpResponse("Password reset successfully! You can now login.")

        except CustomUser.DoesNotExist:
            return HttpResponse("User not found", status=400)

    return HttpResponse("Invalid request method", status=405)