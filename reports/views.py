from rest_framework import viewsets, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.decorators import action
from django.http import HttpResponse
import csv
import io
from reportlab.pdfgen import canvas
from django_filters.rest_framework import DjangoFilterBackend
from level.models import UserLevel, LevelPayment
from level.serializers import PaymentReportSerializer
from .filters import PaymentFilter
from .serializers import DashboardReportSerializer, LevelPaymentReportSerializer
from users.models import CustomUser
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

class PaymentReportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserLevel.objects.all().order_by('-approved_at')
    serializer_class = PaymentReportSerializer
    # permission_classes = [IsAdminUser]  # Uncomment if admin access is required
    filter_backends = [DjangoFilterBackend]
    filterset_class = PaymentFilter

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        pending_qs = queryset.filter(status='pending')
        approved_qs = queryset.filter(status='paid')
        serializer_pending = self.get_serializer(pending_qs, many=True)
        serializer_approved = self.get_serializer(approved_qs, many=True)
        return Response({
            'pending': serializer_pending.data,
            'approved': serializer_approved.data
        })

    @action(detail=False, methods=['get'], url_path='export-csv')
    def export_csv(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="payment_report.csv"'
        writer = csv.writer(response)
        writer.writerow(['Username', 'Level', 'Amount', 'Payment Mode', 'Transaction ID', 'Status', 'Approved At'])
        for obj in queryset:
            writer.writerow([
                getattr(obj.user, 'email', getattr(obj.user, 'user_id', 'Unknown')),
                obj.level.name,
                obj.level.amount,
                obj.payment_mode,
                obj.transaction_id or '',
                obj.status,
                obj.approved_at.strftime('%Y-%m-%d %H:%M:%S') if obj.approved_at else ''
            ])
        return response

    @action(detail=False, methods=['get'], url_path='export-pdf')
    def export_pdf(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer)
        y = 750
        p.drawString(100, y, "Payment Report")
        y -= 20
        p.drawString(100, y, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
        y -= 40
        headers = ['Username', 'Level', 'Amount', 'Payment Mode', 'Transaction ID', 'Status', 'Approved At']
        for i, header in enumerate(headers):
            p.drawString(100 + i * 80, y, header)
        y -= 20
        for obj in queryset:
            row = [
                getattr(obj.user, 'email', getattr(obj.user, 'user_id', 'Unknown')),
                obj.level.name,
                str(obj.level.amount),
                obj.payment_mode,
                obj.transaction_id or '',
                obj.status,
                obj.approved_at.strftime('%Y-%m-%d %H:%M:%S') if obj.approved_at else ''
            ]
            for i, value in enumerate(row):
                p.drawString(100 + i * 80, y, value)
            y -= 20
            if y < 50:
                p.showPage()
                y = 750
        p.showPage()
        p.save()
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="payment_report.pdf"'
        return response

    @action(detail=False, methods=['get'], url_path='export-payment-details-csv')
    def export_payment_details_csv(self, request):
        queryset = LevelPayment.objects.all().order_by('-created_at')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="payment_details_report.csv"'
        writer = csv.writer(response)
        writer.writerow(['Payment ID', 'Payment Token', 'Level Name', 'User ID', 'Username', 'Amount', 'Status', 
                        'Razorpay Order ID', 'Razorpay Payment ID', 'Razorpay Signature', 'Created At'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                str(obj.payment_token),
                obj.user_level.level.name,
                obj.user_level.user.user_id,
                getattr(obj.user_level.user, 'email', getattr(obj.user_level.user, 'user_id', 'Unknown')),
                obj.amount,
                obj.status,
                obj.razorpay_order_id or '',
                obj.razorpay_payment_id or '',
                obj.razorpay_signature or '',
                obj.created_at.strftime('%Y-%m-%d %H:%M:%S') if obj.created_at else ''
            ])
        return response

    @action(detail=False, methods=['get'], url_path='export-payment-details-pdf')
    def export_payment_details_pdf(self, request):
        queryset = LevelPayment.objects.all().order_by('-created_at')
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer)
        y = 750
        p.drawString(100, y, "Payment Details Report")
        y -= 20
        p.drawString(100, y, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
        y -= 40
        headers = ['Payment ID', 'Payment Token', 'Level Name', 'User ID', 'Username', 'Amount', 'Status', 
                  'Razorpay Order ID', 'Razorpay Payment ID', 'Razorpay Signature', 'Created At']
        for i, header in enumerate(headers):
            p.drawString(100 + i * 60, y, header)
        y -= 20
        for obj in queryset:
            row = [
                str(obj.id),
                str(obj.payment_token),
                obj.user_level.level.name,
                obj.user_level.user.user_id,
                getattr(obj.user_level.user, 'email', getattr(obj.user_level.user, 'user_id', 'Unknown')),
                str(obj.amount),
                obj.status,
                obj.razorpay_order_id or '',
                obj.razorpay_payment_id or '',
                obj.razorpay_signature or '',
                obj.created_at.strftime('%Y-%m-%d %H:%M:%S') if obj.created_at else ''
            ]
            for i, value in enumerate(row):
                p.drawString(100 + i * 60, y, value)
            y -= 20
            if y < 50:
                p.showPage()
                y = 750
        p.showPage()
        p.save()
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="payment_details_report.pdf"'
        return response

    @action(detail=False, methods=['get'], url_path='custom-user-report')
    def custom_user_report(self, request):
        logger.debug("Custom user report endpoint hit")
        print("Request path:", request.path)  # Debug the incoming path
        users = CustomUser.objects.filter(is_active=True).prefetch_related('userlevel_set')
        report_data = []

        for user in users:
            user_levels = UserLevel.objects.filter(user=user)
            completed_levels = user_levels.filter(status='paid', level__order__lte=6).count()
            total_received = user_levels.aggregate(total=Sum('received'))['total'] or 0
            received_count = user_levels.filter(status='paid').count()
            refer_help = user_levels.filter(level__name='Refer Help').first()
            refer_help_amount = refer_help.level.amount if refer_help else 0
            refer_help_paid_amount = refer_help_amount if refer_help and refer_help.status == 'paid' else 0
            total_amount_sent = user_levels.filter(status='paid').aggregate(total=Sum('level__amount'))['total'] or 0
            total_amount_received = total_received

            report_data.append({
                'username': f"{user.first_name} {user.last_name}".strip() or user.email,
                'level_completed': completed_levels,
                'received': total_received,
                'received_count': received_count,
                'refer_help_amount': refer_help_amount,
                'amount_if_paid': refer_help_paid_amount,
                'total_amount_sent': total_amount_sent,
                'total_amount_received': total_amount_received
            })

        return Response(report_data)

class DashboardReportViewSet(viewsets.ViewSet):
    # permission_classes = [IsAdminUser]

    def list(self, request):
        # Total members: Count of all active users
        total_members = CustomUser.objects.filter(is_active=True).count()
        logger.debug(f"Total members: {total_members}")

        # Total income: Sum of all received from UserLevel
        total_income = UserLevel.objects.aggregate(total=Sum('received'))['total'] or 0
        logger.debug(f"Total income: {total_income}")

        # Total active level 6: Users with all 6 levels paid (excluding Refer Help)
        active_level_6 = CustomUser.objects.filter(
            userlevel__level__order__lte=6,
            userlevel__status='paid'
        ).annotate(
            paid_levels=Count('userlevel', filter=Q(userlevel__level__order__lte=6, userlevel__status='paid'))
        ).filter(paid_levels=6).distinct().count()
        logger.debug(f"Total active level 6: {active_level_6}")

        # New users on each level: Users with exactly N levels completed (1-6)
        new_users_per_level = []
        for lvl in range(1, 7):
            users_at_level = CustomUser.objects.filter(
                userlevel__level__order__lte=lvl,
                userlevel__status='paid'
            ).annotate(
                paid_levels=Count('userlevel', filter=Q(userlevel__level__order__lte=lvl, userlevel__status='paid'))
            ).filter(paid_levels=lvl).distinct().count()
            new_users_per_level.append({'level': lvl, 'count': users_at_level})
            logger.debug(f"New users at level {lvl}: {users_at_level}")

        # Recent payments: Last 10 verified payments (last 30 days)
        recent_payments_qs = LevelPayment.objects.filter(
            status='Verified',
            created_at__gte=timezone.now() - timedelta(days=30)
        ).order_by('-created_at')[:10]
        recent_payments = LevelPaymentReportSerializer(recent_payments_qs, many=True).data
        logger.debug(f"Recent payments count: {len(recent_payments)}")

        # New user registrations: Last 10 users with username, user_id, levels done (last 30 days)
        recent_users_qs = CustomUser.objects.filter(
            date_of_joining__gte=timezone.now() - timedelta(days=30)
        ).order_by('-date_of_joining')[:10]
        new_user_registrations = []
        for user in recent_users_qs:
            completed_levels = UserLevel.objects.filter(
                user=user, status='paid', level__order__lte=6
            ).count()
            new_user_registrations.append({
                'user_id': user.user_id,
                'username': f"{user.first_name} {user.last_name}".strip() or user.email,
                'levels_done': completed_levels
            })
        logger.debug(f"New user registrations count: {len(new_user_registrations)}")

        data = {
            'total_members': total_members,
            'total_income': total_income,
            'total_active_level_6': active_level_6,
            'new_users_per_level': new_users_per_level,
            'recent_payments': recent_payments,
            'new_user_registrations': new_user_registrations
        }
        serializer = DashboardReportSerializer(data)
        return Response(serializer.data)