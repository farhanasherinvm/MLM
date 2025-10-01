from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
import random
from django.conf import settings
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # Generate 6-digit OTP
            otp = str(random.randint(100000, 999999))
            user.otp = otp
            user.is_active = False  # deactivate user until OTP verified
            user.save()

            # Send OTP to email
            send_mail(
                'Your OTP Code',
                f'Your OTP is: {otp}',
                settings.EMAIL_HOST_USER,
                [user.email],
                fail_silently=False,
            )

           
            return Response({'message': 'User registered successfully. Please verify OTP sent to your email.'}, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    


class ResendOTPView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        phone = request.data.get('phone_number')

        try:
            user = CustomUser.objects.get(phone_number=phone)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        # Generate new OTP
        otp = str(random.randint(100000, 999999))
        user.otp = otp
        user.save()

        send_mail(
            'Your OTP Code',
            f'Your new OTP is: {otp}',
            settings.EMAIL_HOST_USER,
            [user.email],
            fail_silently=False,
        )
        return Response({'message': 'OTP resent successfully'}, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone = request.data.get('phone_number')
        otp = request.data.get('otp')

        try:
            user = CustomUser.objects.get(phone_number=phone)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        if user.otp == otp:
            user.is_active = True
            user.otp = ''
            user.save()
            print(f"User-entered OTP: {otp}, Expected: {user.otp}")

            return Response({'message': 'OTP verified successfully. You can now log in.'}, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        otp = str(random.randint(100000, 999999))
        user.otp = otp
        user.save()

        send_mail(
            'Your Password Reset OTP',
            f'Use this OTP to reset your password: {otp}',
            settings.EMAIL_HOST_USER,
            [email],
            fail_silently=False,
        )

        return Response({'message': 'OTP sent to your email.'}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp')
        new_password = request.data.get('new_password')

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        if user.otp != otp:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.otp = ''
        user.save()

        return Response({'message': 'Password reset successfully.'}, status=status.HTTP_200_OK)



class PasswordResetRequestView(APIView):
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = str(random.randint(100000, 999999))

            # Save OTP to DB
            PasswordResetOTP.objects.create(email=email, otp=otp)

            # Send OTP via Email
            send_mail(
                subject='🔐 Password Reset OTP',
                message=f'Your OTP is: {otp}',
                from_email='your_email@gmail.com',
                recipient_list=[email],
                fail_silently=False,
            )
            
            return Response({'message': '✅ OTP sent successfully to email'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

