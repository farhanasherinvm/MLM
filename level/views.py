from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from .models import Level, UserLevel, LevelPayment, get_referrer_details
from .serializers import (
    LevelSerializer, UserLevelStatusSerializer, UserLevelFinancialSerializer, 
    UserInfoSerializer, LevelRazorpayOrderSerializer, LevelRazorpayVerifySerializer,
    LevelPaymentSerializer, AdminPendingPaymentsSerializer, ManualPaymentSerializer,InitiatePaymentSerializer,CreateDummyUsersSerializer, UpdateLinkedUserIdSerializer, RecipientLevelPaymentSerializer,CreateDummyUsersSerializer, AdminMasterUserSerializer, AdminDummyUserUpdateSerializer
)
from .permissions import IsAdminOrReadOnly,IsPaymentRecipient
from profiles.models import Profile
from django.db import transaction
from django.db.models import F
from users.models import CustomUser
from django.utils import timezone
from django.db.models import Count, Q,Sum
import logging
import razorpay
from django.conf import settings
from .utils import check_and_enforce_payment_lock
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from rest_framework import generics
from level.models import PmfPayment 
from level import constants         
from .serializers import (
    PmfOrderSerializer, 
    PmfVerifySerializer, 
    PmfPaymentSerializer,
    AdminPendingPmfPaymentsSerializer,
    PmfManualPaymentSerializer

)
from rest_framework.permissions import AllowAny
from decimal import Decimal


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

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def enable_payment(self, request, pk=None):
        user_level = self.get_object()
        user_level.pay_enabled = True
        user_level.save()
        logger.info(f"Payment enabled for UserLevel {user_level.id} by admin")
        return Response({
            "message": f"Payment enabled for UserLevel {user_level.id}",
            "user_level_id": user_level.id,
            "pay_enabled": user_level.pay_enabled
        }, status=status.HTTP_200_OK)

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
                        user_level.pay_enabled = True
                        user_level.status = data['status']
                        user_level.save()
                        # Optionally update or create a LevelPayment record to reflect rejection
                        LevelPayment.objects.update_or_create(
                            user_level=user_level,
                            defaults={'status': 'Failed', 'amount': user_level.level.amount}
                        )
                    else:
                        user_level.status = data['status']
                        user_level.save()
                        # Create or update LevelPayment to reflect the pending status
                        LevelPayment.objects.update_or_create(
                            user_level=user_level,
                            defaults={'status': 'Pending' if data['status'] == 'pending' else 'Failed', 'amount': user_level.level.amount}
                        )
                
                serializer = self.get_serializer(user_level)
                return Response(serializer.data)

            if 'withdraw' in data and data['withdraw']:
                if user_level.status != 'paid':
                    return Response(
                        {'error': 'Level not paid.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Check if the latest payment is verified
                latest_payment = LevelPayment.objects.filter(user_level=user_level).order_by('-created_at').first()
                if not latest_payment or latest_payment.status != 'Verified':
                    return Response(
                        {'error': 'Payment not verified.'},
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
                # status='not_paid' or 'rejected'
                status__in=['not_paid', 'rejected'],
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

class ManualPaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ManualPaymentSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        
        # --- FIX: Retrieve the validated UserLevel object directly ---
        user_level = validated_data.get('user_level_instance')

        if LevelPayment.objects.filter(user_level=user_level, status='Pending', payment_method='Manual').exists():
             return Response(
                {"error": "A manual payment for this level is already pending admin review."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        # --- End FIX

        payment_proof = serializer.validated_data.get('payment_proof')
        level_payment = LevelPayment.objects.create(
            user_level=user_level,
            amount=user_level.level.amount,
            status="Pending",
            payment_method="Manual",
            payment_proof=payment_proof
        )

        with transaction.atomic():
            user_level.status = 'pending'
            user_level.payment_mode = 'Manual'
            user_level.save()

        logger.info(f"Manual payment submitted for LevelPayment {level_payment.id} (user: {request.user.user_id}, level: {user_level.level.name})")

        return Response({
            "message": "Manual payment details uploaded successfully. Status changed to pending. Awaiting admin verification.",
            "payment_token": str(level_payment.payment_token),
            "payment_data": LevelPaymentSerializer(level_payment, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

class LevelPaymentViewSet(viewsets.ModelViewSet):
    queryset = LevelPayment.objects.all()
    serializer_class = LevelPaymentSerializer
    permission_classes = [IsAdminUser]

    def get_serializer_class(self):
        if self.action == 'pending':
            return AdminPendingPaymentsSerializer
        return LevelPaymentSerializer

    def get_queryset(self):
        if self.action == 'pending':
            return self.queryset.filter(status='Pending', payment_method='Manual').order_by('-created_at')
        return self.queryset.all().order_by('-created_at')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    @action(detail=False, methods=['get'], url_path='pending')
    def pending(self, request):
        """List all pending manual payments for admin review."""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        level_payment = self.get_object()
        if level_payment.payment_method != "Manual" or level_payment.status != "Pending":
            return Response({"error": "Only pending manual payments can be verified."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            level_payment.status = "Verified"
            level_payment.save()

        logger.info(f"Manual payment verified for LevelPayment {level_payment.id} by admin")

        return Response({
            "message": "Payment verified and level marked as paid",
            "payment_data": self.get_serializer(level_payment).data
        })

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        level_payment = self.get_object()
        if level_payment.payment_method != "Manual" or level_payment.status != "Pending":
            return Response({"error": "Only pending manual payments can be rejected."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            level_payment.status = "Failed"
            level_payment.save()
            user_level = level_payment.user_level
            user_level.status = 'rejected'
            user_level.pay_enabled = True
            user_level.save()

        logger.info(f"Manual payment rejected for LevelPayment {level_payment.id} by admin")

        return Response({
            "message": "Payment rejected",
            "payment_data": self.get_serializer(level_payment).data
        })

class RecipientPaymentViewSet(viewsets.GenericViewSet):
    
    # Use IsAuthenticated for base access. IsPaymentRecipient handles object-level security.
    permission_classes = [IsAuthenticated, IsPaymentRecipient]
    queryset = LevelPayment.objects.all()
    serializer_class = RecipientLevelPaymentSerializer
    lookup_field = 'payment_token' 
    def get_queryset(self):
        # 1. Filter by the current user as the recipient (linked_user_id)
        # 2. Filter for only pending manual payments
        user_id = str(self.request.user.user_id)
        
        # Find all UserLevels where the current user is the linked_user
        # Then filter LevelPayments based on those UserLevels
        
        # A more efficient way (requires a related_name/lookup):
        # We need to filter LevelPayment based on the linked_user_id of its related UserLevel.
        return self.queryset.filter(
            user_level__linked_user_id=user_id,
            status='Pending',
            payment_method='Manual'
        ).order_by('-created_at')

    # Endpoint: GET /api/recipient/payments/
    def list(self, request):
        """List all pending manual payments waiting for the current user's verification."""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Note: You must uncomment and configure your serializer_class for this to work
        serializer = self.get_serializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    # Endpoint: POST /api/recipient/payments/{payment_token}/accept/
    @action(detail=True, methods=['post'], url_path='accept')
    def accept(self, request, payment_token=None):
        level_payment = self.get_object() # Fetches object and applies IsPaymentRecipient

        # Redundant checks as get_queryset filters already, but good for safety/consistency
        if level_payment.payment_method != "Manual" or level_payment.status != "Pending":
            return Response({"error": "Payment is not a pending manual payment."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            level_payment.status = "Verified"
            level_payment.save(update_fields=['status']) # Triggers signals
        
        logger.info(f"Manual payment accepted for LevelPayment {level_payment.id} by linked user {request.user.user_id}")

        return Response({
            "message": "Payment accepted and level marked as paid for the payer. Your balance is updated."
        })

    # Endpoint: POST /api/recipient/payments/{payment_token}/reject/
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, payment_token=None):
        level_payment = self.get_object() # Fetches object and applies IsPaymentRecipient

        if level_payment.payment_method != "Manual" or level_payment.status != "Pending":
            return Response({"error": "Payment is not a pending manual payment."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            level_payment.status = "Failed"
            level_payment.save(update_fields=['status']) # Update LevelPayment status
            
            # Optionally update the payer's UserLevel to 'rejected' and disable payment
            user_level = level_payment.user_level
            user_level.status = 'rejected'
            user_level.pay_enabled = True
            user_level.save(update_fields=['status', 'pay_enabled'])

        logger.info(f"Manual payment rejected for LevelPayment {level_payment.id} by linked user {request.user.user_id}")

        return Response({
            "message": "Payment rejected. Payer's status updated."
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


class InitiatePaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = InitiatePaymentSerializer(data=request.data,context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST,)

  
        user_level = serializer.validated_data['user_level_instance']
        payment_method = serializer.validated_data['payment_method']

        # --- BEGIN: LOCK ENFORCEMENT CHECK ---
        referrer = None
        if user_level.linked_user_id:
            try:
                # Fetch the referrer to check their lock status
                referrer = CustomUser.objects.get(user_id=user_level.linked_user_id)
            except CustomUser.DoesNotExist:
                # Log a warning, but often the payment should proceed if the referrer is missing
                logger.warning(f"Payment initiation error: Referrer not found for linked_user_id: {user_level.linked_user_id}")
                # Set referrer to None to continue, assuming payment goes to admin/platform or is blocked later.
                referrer = None 
            
            if referrer:
                level_amount = user_level.level.amount
                # Check if the referrer (receiving user) is locked
                can_pay, message = check_and_enforce_payment_lock(referrer, level_amount)
                
                if not can_pay:
                    # BLOCK PAYMENT: Referrer is locked from receiving.
                    return Response({
                        "error": "Payment Blocked",
                        "detail": message, 
                        "referrer_id": referrer.user_id,
                        "level_name": user_level.level.name,
                    }, status=status.HTTP_403_FORBIDDEN)
        # --- END: LOCK ENFORCEMENT CHECK ---

        
        if payment_method == 'Razorpay':
            
            # The referrer fetching logic is repeated here from the lock check, 
            # but we keep it to ensure 'referrer' is defined for the details section below
            if not referrer and user_level.linked_user_id:
                try:
                    referrer = CustomUser.objects.get(user_id=user_level.linked_user_id)
                except CustomUser.DoesNotExist:
                    pass

            level_payment = LevelPayment.objects.create(
                user_level=user_level,
                amount=user_level.level.amount,
                status="Pending",
                payment_method="Razorpay"
            )
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

            level_payment.razorpay_order_id = order["id"]
            level_payment.save()

            logger.info(f"Razorpay order {order['id']} created for LevelPayment {level_payment.id} (user: {request.user.user_id}, level: {user_level.level.name})")

            # Fetch upi_number from CustomUser or Profile
            upi_number = 'N/A'
            if referrer:
                upi_number = getattr(referrer, 'upi_number', 'N/A')
                if upi_number == 'N/A':
                    try:
                        # Assuming Profile model is defined and accessible
                        profile = Profile.objects.get(user=referrer) 
                        upi_number = getattr(profile, 'upi_number', 'N/A')
                    except Profile.DoesNotExist:
                        pass

            referrer_details = {
                'upi_number': upi_number,
                'user_id': getattr(referrer, 'user_id', 'N/A') if referrer else 'N/A',
                'full_name': f"{getattr(referrer, 'first_name', '')} {getattr(referrer, 'last_name', '')}".strip() if referrer else 'N/A'
            }

            return Response({
                "payment_method": "Razorpay",
                "payment_token": str(level_payment.payment_token),
                "order_id": order["id"],
                "amount": user_level.level.amount,
                "currency": "INR",
                "razorpay_key": settings.RAZORPAY_KEY_ID,
                "referrer_details": referrer_details,
                "level_name": user_level.level.name,
                "payment_amount": user_level.level.amount
            }, status=status.HTTP_201_CREATED)

        else:  # Manual
            
            # The referrer fetching logic is repeated here from the lock check, 
            # but we keep it to ensure 'referrer' is defined for the details section below
            if not referrer and user_level.linked_user_id:
                try:
                    referrer = CustomUser.objects.get(user_id=user_level.linked_user_id)
                except CustomUser.DoesNotExist:
                    pass
                    
            # Fetch upi_number from CustomUser or Profile
            upi_number = 'N/A'
            if referrer:
                upi_number = getattr(referrer, 'upi_number', 'N/A')
                if upi_number == 'N/A':
                    try:
                        # Assuming Profile model is defined and accessible
                        profile = Profile.objects.get(user=referrer) 
                        upi_number = getattr(profile, 'upi_number', 'N/A')
                    except Profile.DoesNotExist:
                        pass

            referrer_details = {
                'upi_number': upi_number,
                'user_id': getattr(referrer, 'user_id', 'N/A') if referrer else 'N/A',
                'full_name': f"{getattr(referrer, 'first_name', '')} {getattr(referrer, 'last_name', '')}".strip() if referrer else 'N/A'
            }
            
            # The rest of the manual payment flow continues...

            return Response({
                "payment_method": "Manual",
                "message": "Proceed to upload payment proof",
                "user_level_id": user_level.id,
                "referrer_details": referrer_details,
                "level_name": user_level.level.name,
                "payment_amount": user_level.level.amount
            }, status=status.HTTP_200_OK)




class UpdateLinkedUserIdView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        try:
            user_level = UserLevel.objects.get(pk=pk)
        except UserLevel.DoesNotExist:
            return Response({"error": "UserLevel not found"}, status=404)

        serializer = UpdateLinkedUserIdSerializer(user_level, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "linked_user_id updated successfully", "data": serializer.data})
        return Response(serializer.errors, status=400)



class CreateDummyUsers(generics.CreateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = CreateDummyUsersSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user_level_instance = serializer.save()
        
        response_serializer = DummyUserSerializer(user_level_instance, context={'request': request})
        
        return Response({
            "message": f"Master Node {user_level_instance.user.user_id} created successfully.",
            "data": response_serializer.data
        }, status=status.HTTP_201_CREATED)

# =========================================================================
# B. Endpoint for Listing All Dummy/Master Users (GET)
# URL: /api/dummy-users/
# =========================================================================
class DummyUserViewSet(viewsets.ReadOnlyModelViewSet):
    # Set the queryset base to CustomUser model
    # Use Prefetch to efficiently fetch all related UserLevel data in one query
    queryset = CustomUser.objects.filter(
        user_id__startswith='MASTER' # Initial filter for dummy users
    ).prefetch_related(
        'userlevel_set' 
    ).order_by('-date_of_joining') 
    
    # Use the new serializer that handles CustomUser objects
    serializer_class = AdminMasterUserSerializer # <-- REQUIRES NEW SERIALIZER (See below)
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        # We handle the main filtering and ordering in the queryset attribute, 
        # but ensure distinct users if necessary (though prefetch handles efficiency).
        return super().get_queryset().distinct() 

class AdminDummyUserControlView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        try:
            # 🟢 CRITICAL FIX 1: Fetch CustomUser instead of UserLevel
            user_to_update = CustomUser.objects.get(pk=pk)
            
            # 🟢 Filter check on CustomUser object
            if not (user_to_update.user_id.startswith('DUMMY') or user_to_update.user_id.startswith('MASTER') or user_to_update.user_id.startswith('FAKEDATA')):
                return Response({"error": "Only dummy/master users can be modified via this endpoint."}, status=status.HTTP_403_FORBIDDEN)
                
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        # 🟢 CRITICAL FIX 2: Pass CustomUser instance to the corrected serializer
        serializer = AdminDummyUserUpdateSerializer(user_to_update, data=request.data, partial=True, context={'request': request})
        
        if serializer.is_valid():
            updated_user = serializer.save()
            
            # 🟢 CRITICAL FIX 3: Use the AdminMasterUserSerializer for the response
            # (Assuming you use the serializer designed to display one record per user)
            response_data = AdminMasterUserSerializer(updated_user, context={'request': request}).data
            
            return Response({"message": "Dummy user details updated successfully", "data": response_data}, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        try:
            # 🟢 CRITICAL FIX 1: Fetch CustomUser instead of UserLevel
            user_to_delete = CustomUser.objects.get(pk=pk)
            
            # 🟢 Filter check on CustomUser object
            if not (user_to_delete.user_id.startswith('DUMMY') or user_to_delete.user_id.startswith('MASTER') or user_to_delete.user_id.startswith('FAKEDATA')):
                return Response({"error": "Only dummy/master users can be deleted via this endpoint."}, status=status.HTTP_403_FORBIDDEN)
                
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        # Deleting the CustomUser instance will automatically cascade and delete 
        # all related UserLevel records (assuming you have cascade deletion set up).
        user_to_delete.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)


class PmfOrderView(APIView):
    """Creates a PmfPayment record and a Razorpay Order ID for the PMF fee."""
    permission_classes = [IsAuthenticated] 
    
    def post(self, request):
        if not razorpay_client:
            return Response({"error": "Payment service not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
        serializer = PmfOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pmf_part = serializer.validated_data.get('pmf_part')
        
        # 1. Determine amount and tags
        if pmf_part == 'part_1':
            amount = constants.PMF_PART_1_AMOUNT
            pmf_type_tag = 'PMF_PART_1'
            # Optional: Check if part 1 is already paid
            if request.user.pmf_status != constants.PMF_STATUS_NOT_PAID:
                 return Response({"error": "PMF Part 1 already paid."}, status=status.HTTP_400_BAD_REQUEST)
        elif pmf_part == 'part_2':
            amount = constants.PMF_PART_2_AMOUNT
            pmf_type_tag = 'PMF_PART_2'
            # Optional: Check if part 2 is already paid or part 1 is unpaid
            if request.user.pmf_status != constants.PMF_STATUS_PART_1_PAID:
                 return Response({"error": "PMF Part 2 cannot be paid yet or is already paid."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "Invalid PMF part specified."}, status=status.HTTP_400_BAD_REQUEST)

        amount_float = float(amount)
        amount_paisa = int(amount_float * 100)
        
        # 2. Create PmfPayment record
        try:
            pmf_payment = PmfPayment.objects.create(
                user=request.user, 
                amount=amount_float,
                status='Pending',
                pmf_type=pmf_type_tag,
            )
        except Exception as e:
            logger.error(f"Failed to create PMF payment record for {request.user.user_id}: {e}")
            return Response({"error": "Failed to initiate payment record."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 3. Create Razorpay Order
        try:
            order = razorpay_client.order.create({ 
                "amount": amount_paisa,
                "currency": "INR",
                "payment_capture": 1,
            })
        except Exception as e:
            logger.error(f"Razorpay PMF order creation failed for payment {pmf_payment.id}: {e}")
            pmf_payment.status = "Failed"
            pmf_payment.save(update_fields=["status"])
            return Response({"error": "Failed to create payment order"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        pmf_payment.razorpay_order_id = order.get("id")
        pmf_payment.save(update_fields=["razorpay_order_id"])

        # 4. Return Order details
        return Response({
            "order_id": order.get("id"),
            "amount": str(amount_float),
            "currency": "INR",
            "razorpay_key": settings.RAZORPAY_KEY_ID,
            "pmf_payment_id": pmf_payment.id, # Pass new ID to frontend for verification
        }, status=status.HTTP_201_CREATED)


class PmfVerifyView(APIView):
    """Verifies Razorpay signature and updates the CustomUser's pmf_status for PMF."""
    permission_classes = [AllowAny] 

    def post(self, request):
        serializer = PmfVerifySerializer(data=request.data)
        if not serializer.is_valid():
             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
             
        data = serializer.validated_data

        try:
            # Look up PmfPayment by order ID
            pmf_payment = PmfPayment.objects.get(
                razorpay_order_id=data["razorpay_order_id"], status="Pending"
            )
        except PmfPayment.DoesNotExist:
            return Response({"error": "PMF Payment not found or already processed"}, status=status.HTTP_404_NOT_FOUND)

        # 1. Verify signature 
        verification_ok = False
        if getattr(settings, "RAZORPAY_TEST_MODE", False): # Assume test mode is False unless explicitly set
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
                logger.error(f"Razorpay signature failed for PMF {pmf_payment.id}: {e}")
                verification_ok = False

        if not verification_ok:
            pmf_payment.status = "Failed"
            pmf_payment.save(update_fields=["status"])
            return Response({"error": "Signature verification failed"}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Mark Verified and Update User Status atomically
        with transaction.atomic():
            # Update PmfPayment record
            pmf_payment.razorpay_payment_id = data["razorpay_payment_id"]
            pmf_payment.razorpay_signature = data["razorpay_signature"]
            pmf_payment.status = "Verified"
            pmf_payment.save(update_fields=["razorpay_payment_id", "razorpay_signature", "status"])

            user = pmf_payment.user
            
            # Update CustomUser.pmf_status field
            if pmf_payment.pmf_type == 'PMF_PART_1':
                user.pmf_status = constants.PMF_STATUS_PART_1_PAID
            elif pmf_payment.pmf_type == 'PMF_PART_2':
                user.pmf_status = constants.PMF_STATUS_PAID 
            
            user.save(update_fields=['pmf_status'])

        logger.info(f"PMF Payment {pmf_payment.id} verified. User {user.user_id} status updated to {user.pmf_status}.")
        
        return Response({
            "message": f"{pmf_payment.pmf_type} verified successfully. Account unlocked.",
            "user_id": user.user_id,
        }, status=status.HTTP_200_OK)


class PmfStatusView(APIView):
    """
    Returns the current user's PMF payment status, the next PMF part due, 
    and whether the user is currently locked based on their received amount vs. the cap.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        current_status = user.pmf_status
        
        # 1. Calculate Total Received Amount (Excluding Fee Levels)
        FEE_LEVEL_NAMES = [
            constants.LOCK_LEVEL_NAME, 
            constants.PMF_PART_1_NAME, 
            constants.PMF_PART_2_NAME
        ]
        
        aggregation_result = UserLevel.objects.filter(user=user)\
            .exclude(level__name__in=FEE_LEVEL_NAMES)\
            .aggregate(total_received=Sum('received'))

        total_received = aggregation_result['total_received'] or Decimal('0.00')

        # 2. Determine PMF Status and Next Action
        next_pmf_part = "None"
        amount_due = Decimal('0.00')
        current_cap_threshold = None
        is_locked = False
        lock_message = "Payment allowed: No cap reached or fully paid."
        
        # Determine the current relevant cap and next required payment
        if current_status == constants.PMF_STATUS_NOT_PAID:
            current_cap_threshold = constants.CAP_1_AMOUNT
            next_pmf_part = constants.PMF_PART_1_NAME
            amount_due = constants.PMF_PART_1_AMOUNT
            
        elif current_status == constants.PMF_STATUS_PART_1_PAID:
            current_cap_threshold = constants.CAP_2_AMOUNT
            next_pmf_part = constants.PMF_PART_2_NAME
            amount_due = constants.PMF_PART_2_AMOUNT
            
        elif current_status == constants.PMF_STATUS_PAID:
            # Fully Paid: No cap restriction (other than the base R4700 level, which is handled elsewhere)
            current_cap_threshold = Decimal('999999999.00') # Effectively unlimited
            lock_message = "Fully unlocked. All PMF fees paid."
            

        # 3. Apply Locking Logic (Check if the relevant cap is reached)
        if current_cap_threshold is not None:
            if total_received >= current_cap_threshold and current_status != constants.PMF_STATUS_PAID:
                is_locked = True
                lock_message = f"R{current_cap_threshold} cap reached. Pay {next_pmf_part} to unlock."
            
            # Special case for the base R4700 cap logic (already exists in check_and_enforce_payment_lock)
            # We explicitly check here only if no PMF cap was hit.
            elif total_received >= constants.PAYMENT_CAP_AMOUNT and not is_locked:
                 # Logic for the base R4700 lock (Refer Help Level)
                 try:
                    refer_help_level = UserLevel.objects.get(
                        user=user, 
                        level__name=constants.LOCK_LEVEL_NAME
                    )
                    if refer_help_level.status != 'paid':
                        is_locked = True
                        current_cap_threshold = constants.PAYMENT_CAP_AMOUNT
                        next_pmf_part = constants.LOCK_LEVEL_NAME # Use the old lock name
                        amount_due = refer_help_level.level.amount
                        lock_message = f"R{constants.PAYMENT_CAP_AMOUNT} cap reached. Pay the '{constants.LOCK_LEVEL_NAME}' level to unlock."
                 except UserLevel.DoesNotExist:
                     pass # Assume admin/system setup handles this if missing

        # 4. Final Response Structure
        return Response({
            "user_id": user.user_id,
            "pmf_status": current_status,
            "total_received_amount": total_received,
            "next_pmf_part_due": next_pmf_part,
            "amount_due": amount_due,
            "current_payment_cap": current_cap_threshold,
            "is_payment_locked": is_locked,
            "lock_details": lock_message # Helpful for debugging/frontend messages
        }, status=status.HTTP_200_OK)


class PmfManualPaymentView(APIView):
    """Handles manual submission of PMF payment proof."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Using the PmfManualPaymentSerializer you provided earlier
        serializer = PmfManualPaymentSerializer(data=request.data) 
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        pmf_part = validated_data.get('pmf_part')
        payment_proof = validated_data.get('payment_proof')
        user = request.user
        
        # 1. Determine amount and check eligibility (using user.pmf_status)
        if pmf_part == 'part_1':
            amount = constants.PMF_PART_1_AMOUNT
            pmf_type_tag = 'PMF_PART_1'
            if user.pmf_status != constants.PMF_STATUS_NOT_PAID:
                 return Response({"error": "PMF Part 1 is already paid or in process."}, status=status.HTTP_400_BAD_REQUEST)
        elif pmf_part == 'part_2':
            amount = constants.PMF_PART_2_AMOUNT
            pmf_type_tag = 'PMF_PART_2'
            if user.pmf_status != constants.PMF_STATUS_PART_1_PAID:
                 return Response({"error": "PMF Part 2 cannot be paid yet or is already paid."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "Invalid PMF part specified."}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Check for existing Pending manual payment
        if PmfPayment.objects.filter(user=user, pmf_type=pmf_type_tag, status='Pending', payment_method='Manual').exists():
            return Response({"error": "A manual payment for this PMF part is already pending admin review."}, status=status.HTTP_400_BAD_REQUEST)

        # 3. Create PmfPayment record
        try:
            pmf_payment = PmfPayment.objects.create(
                user=user, 
                amount=float(amount),
                status='Pending', 
                pmf_type=pmf_type_tag,
                payment_method='Manual', # <--- Set the method
                payment_proof=payment_proof # <--- Store the proof
            )
        except Exception as e:
            logger.error(f"Failed to create Manual PMF payment record for {user.user_id}: {e}")
            return Response({"error": "Failed to initiate manual payment record."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "message": "Manual payment proof submitted successfully. Awaiting admin verification.",
            "pmf_payment_id": pmf_payment.id,
        }, status=status.HTTP_201_CREATED)


class PmfPaymentViewSet(viewsets.ModelViewSet):
    """
    Admin ViewSet for managing and verifying manual PMF payments.
    """
    queryset = PmfPayment.objects.all()
    serializer_class = PmfPaymentSerializer
    permission_classes = [IsAdminUser]

    def get_serializer_class(self):
        # Use a detailed serializer for pending list to show payment proof
        if self.action == 'pending':
            return AdminPendingPmfPaymentsSerializer
        return PmfPaymentSerializer

    def get_queryset(self):
        # Custom queryset for the 'pending' action
        if self.action == 'pending':
            return self.queryset.filter(status='Pending', payment_method='Manual').order_by('-created_at')
        return self.queryset.all().order_by('-created_at')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    # ------------------------------------------------------------------
    # Action: List Pending Payments (GET /api/pmf-payments/pending/)
    # ------------------------------------------------------------------
    @action(detail=False, methods=['get'], url_path='pending')
    def pending(self, request):
        """List all pending manual PMF payments for admin review."""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Action: Verify Payment (POST /api/pmf-payments/{pk}/verify/)
    # ------------------------------------------------------------------
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        pmf_payment = self.get_object()

        if pmf_payment.payment_method != "Manual" or pmf_payment.status != "Pending":
            return Response({"error": "Only pending manual payments can be verified."}, status=status.HTTP_400_BAD_REQUEST)

        user = pmf_payment.user

        with transaction.atomic():
            # 1. Update PmfPayment status
            pmf_payment.status = "Verified"
            pmf_payment.save(update_fields=['status'])

            # 2. Determine and Update CustomUser PMF status
            if pmf_payment.pmf_type == 'PMF_PART_1':
                user.pmf_status = constants.PMF_STATUS_PART_1_PAID
            elif pmf_payment.pmf_type == 'PMF_PART_2':
                user.pmf_status = constants.PMF_STATUS_PAID
            
            user.save(update_fields=['pmf_status']) # Save the user status change

        logger.info(f"Manual PMF payment verified for {pmf_payment.id} by admin {request.user.user_id}")

        return Response({
            "message": f"PMF {pmf_payment.pmf_type} payment verified and user status updated to {user.pmf_status}.",
            "payment_data": self.get_serializer(pmf_payment).data
        }, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Action: Reject Payment (POST /api/pmf-payments/{pk}/reject/)
    # ------------------------------------------------------------------
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        pmf_payment = self.get_object()

        if pmf_payment.payment_method != "Manual" or pmf_payment.status != "Pending":
            return Response({"error": "Only pending manual payments can be rejected."}, status=status.HTTP_400_BAD_REQUEST)

        # For PMF rejection, we only need to mark the payment as failed.
        # The user's pmf_status should generally not be affected by a failed/rejected attempt, 
        # as they remain in the 'NOT_PAID' or 'PART_1_PAID' state, allowing them to try again.
        with transaction.atomic():
            pmf_payment.status = "Failed"
            pmf_payment.save(update_fields=['status'])
            
        logger.info(f"Manual PMF payment rejected for {pmf_payment.id} by admin {request.user.user_id}")

        return Response({
            "message": "Manual payment rejected. User's PMF status is unchanged, and they can resubmit proof or use Razorpay.",
            "payment_data": self.get_serializer(pmf_payment).data
        }, status=status.HTTP_200_OK)