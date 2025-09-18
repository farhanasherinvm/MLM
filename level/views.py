from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from .models import Level, UserLevel, LevelPayment, get_referrer_details
from .serializers import (
    LevelSerializer, UserLevelStatusSerializer, UserLevelFinancialSerializer, 
    UserInfoSerializer, LevelRazorpayOrderSerializer, LevelRazorpayVerifySerializer,
    LevelPaymentSerializer
)
from .permissions import IsAdminOrReadOnly
from profiles.models import Profile
from django.db import transaction
from django.db.models import F
from users.models import CustomUser
from django.utils import timezone
from django.db.models import Count, Q
import logging
import razorpay
from django.conf import settings

logger = logging.getLogger(__name__)

razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

class LevelViewSet(viewsets.ModelViewSet):
    queryset = Level.objects.all()
    serializer_class = LevelSerializer
    # permission_classes = [IsAdminUser]

class UserLevelViewSet(viewsets.ModelViewSet):
    queryset = UserLevel.objects.all()
    serializer_class = UserLevelStatusSerializer
    # permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        if getattr(self, 'action', '') == 'financial':
            return UserLevelFinancialSerializer
        return UserLevelStatusSerializer

    @action(detail=False, methods=['get'])
    def financial(self, request):
        user_levels = self.get_queryset().exclude(level__name='Refer Help')
        serializer = UserLevelFinancialSerializer(user_levels, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def referrer_details(self, request, pk=None):
        user_level = self.get_object()
        if not user_level.linked_user_id:
            return Response(
                {"error": "No referrer associated with this level."},
                status=status.HTTP_404_NOT_FOUND
            )
        details = get_referrer_details(user_level.linked_user_id)
        if not details:
            return Response(
                {"error": "Referrer details not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(details)

    @action(detail=False, methods=['get'])
    def user_info(self, request):
        serializer = UserInfoSerializer({'user': request.user})
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        user_level = self.get_object()
        data = request.data

        if 'status' in data:
            if data['status'] not in ['not_paid', 'paid', 'pending', 'rejected']:
                return Response(
                    {'error': 'Invalid status value. Use "not_paid", "paid", "pending", or "rejected".'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                if data['status'] == 'paid':
                    return Response(
                        {'error': 'Directly marking as paid is disabled. Use Razorpay payment flow.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                elif data['status'] == 'rejected':
                    user_level.pay_enabled = False
                    user_level.status = data['status']
                    user_level.save()
                else:
                    user_level.status = data['status']
                    user_level.save()
            
            serializer = self.get_serializer(user_level)
            return Response(serializer.data)

        if 'withdraw' in data and data['withdraw']:
            if user_level.status != 'paid':
                return Response(
                    {'error': 'Level not paid.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if user_level.level.name == 'Refer Help':
                return Response(
                    {'error': 'Withdraw not applicable for Refer Help.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            profile = Profile.objects.get(user=user_level.user)
            if hasattr(profile, 'referrals') and profile.referrals.count() < 2:
                return Response(
                    {'error': 'Must have referred 2 persons to withdraw.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if user_level.balance <= 0:
                return Response(
                    {'error': 'No balance to withdraw.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            withdraw_amount = user_level.balance
            if user_level.received + withdraw_amount > user_level.target:
                return Response(
                    {'error': 'Received amount would exceed target.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                UserLevel.objects.filter(id=user_level.id).update(
                    received=F('received') + withdraw_amount,
                    balance=F('balance') - withdraw_amount
                )

            serializer = self.get_serializer(user_level)
            return Response({'success': f'Withdrawn {withdraw_amount} to received.', 'data': serializer.data})

        return super().partial_update(request, pk)

    def _check_and_enable_referring(self, user):
        """Check if all UserLevels (including Refer Help) are paid and enable referring."""
        user_levels = UserLevel.objects.filter(user=user)
        if user_levels.filter(status='paid').count() == user_levels.count():
            try:
                profile = Profile.objects.get(user=user)
                profile.eligible_to_refer = True
                profile.save()
            except Profile.DoesNotExist:
                logger.warning(f"No Profile found for user {user.user_id} when enabling referring")

class RazorpayOrderForLevelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LevelRazorpayOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_level = UserLevel.objects.get(
                id=serializer.validated_data['user_level_id'],
                user=request.user,
                status='not_paid',
                is_active=True,
                pay_enabled=True
            )
        except UserLevel.DoesNotExist:
            return Response({"error": "UserLevel not found, already paid, or payment not enabled"}, status=status.HTTP_404_NOT_FOUND)

        # Create LevelPayment
        level_payment = LevelPayment.objects.create(
            user_level=user_level,
            amount=user_level.level.amount,
            status="Pending"
        )

        # Create Razorpay order
        amount_paisa = int(user_level.level.amount * 100)
        try:
            order = razorpay_client.order.create({
                "amount": amount_paisa,
                "currency": "INR",
                "payment_capture": 1
            })
        except Exception as e:
            logger.error(f"Razorpay order creation failed: {str(e)}")
            level_payment.status = "Failed"
            level_payment.save()
            return Response({"error": "Failed to create payment order"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Update LevelPayment with order details
        level_payment.razorpay_order_id = order["id"]
        level_payment.save()

        logger.info(f"Razorpay order {order['id']} created for LevelPayment {level_payment.id} (user: {request.user.user_id}, level: {user_level.level.name})")

        return Response({
            "payment_token": str(level_payment.payment_token),
            "order_id": order["id"],
            "amount": user_level.level.amount,
            "currency": "INR",
            "razorpay_key": settings.RAZORPAY_KEY_ID,
        }, status=status.HTTP_201_CREATED)

class RazorpayVerifyForLevelView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LevelRazorpayVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            level_payment = LevelPayment.objects.get(
                payment_token=data["payment_token"],
                razorpay_order_id=data["razorpay_order_id"],
                status="Pending"
            )
        except LevelPayment.DoesNotExist:
            return Response({"error": "Payment not found or already processed"}, status=status.HTTP_404_NOT_FOUND)

        # Verify signature
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
                logger.error(f"Signature verification failed: {str(e)}")
                verification_ok = False

        if not verification_ok:
            level_payment.status = "Failed"
            level_payment.save()
            return Response({"error": "Signature verification failed"}, status=status.HTTP_400_BAD_REQUEST)

        # Update LevelPayment and trigger UserLevel update
        with transaction.atomic():
            level_payment.status = "Verified"
            level_payment.razorpay_payment_id = data["razorpay_payment_id"]
            level_payment.razorpay_signature = data["razorpay_signature"]
            level_payment.save()  # Triggers post_save signal to update UserLevel

        logger.info(f"Payment verified for LevelPayment {level_payment.id} (user: {level_payment.user_level.user.user_id}, level: {level_payment.user_level.level.name})")

        return Response({
            "message": "Payment verified and level marked as paid",
            "payment_data": LevelPaymentSerializer(level_payment).data
        })

class LevelCompletionViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['get'], url_path='completion-stats')
    def completion_stats(self, request):
        logger.debug("Level completion stats endpoint hit for user %s", request.user.user_id)
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=400)

        user = request.user
        referred_users = CustomUser.objects.filter(sponsor_id=user.user_id)
        all_users = [user] + list(referred_users)

        total_users = CustomUser.objects.filter(userlevel__user__in=all_users).distinct().count()
        if total_users == 0:
            return Response({"error": "No users found in the network"}, status=400)

        all_levels = Level.objects.all().order_by('order')
        user_levels = UserLevel.objects.filter(user__in=all_users, status='paid')

        # Aggregate completion stats for each level
        completion_stats = []
        for level in all_levels:
            completed_count = user_levels.filter(level=level).count()
            percentage = (completed_count / total_users) * 100 if total_users > 0 else 0
            completion_stats.append({
                'level_name': level.name,
                'completed_count': completed_count,
                'percentage': round(percentage, 2)  # Rounded to 2 decimal places
            })

        data = {
            'completion_stats': completion_stats
        }
        return Response(data)