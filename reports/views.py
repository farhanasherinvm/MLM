from rest_framework import viewsets, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.decorators import action
from django.http import HttpResponse
import csv
import io
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from django_filters.rest_framework import DjangoFilterBackend
from level.models import UserLevel, LevelPayment
from level.serializers import PaymentReportSerializer
from .filters import PaymentFilter
from .serializers import DashboardReportSerializer, LevelPaymentReportSerializer, SendRequestReportSerializer, AUCReportSerializer, PaymentReportSerializer, LevelUsersSerializer,BonusSummarySerializer
from users.models import CustomUser
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from openpyxl import Workbook

import logging

logger = logging.getLogger(__name__)

# Existing PaymentReportViewSet (unchanged for now)
class PaymentReportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserLevel.objects.all().order_by('-approved_at')
    serializer_class = PaymentReportSerializer
    permission_classes = [IsAdminUser]  # Uncomment if admin access is required
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
            'approved': serializer_approved.data,
        })

    @action(detail=False, methods=['get'], url_path='export-csv')
    def export_csv(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="payment_report.csv"'
        writer = csv.writer(response)
        writer.writerow(['Username', 'Level', 'Amount', 'Payment_Mode', 'Transaction_ID', 'Status', 'Approved_At'])
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
        headers = ['Username', 'Level', 'Amount', 'Payment_Mode', 'Transaction_ID', 'Status', 'Approved_At']
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
        writer.writerow(['Payment_ID', 'Payment_Token', 'Level_Name', 'User_ID', 'Username', 'Amount', 'Status', 
                        'Razorpay_Order_ID', 'Razorpay_Payment_ID', 'Razorpay_Signature', 'Created_At'])
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
        headers = ['Payment_ID', 'Payment_Token', 'Level_Name', 'User_ID', 'Username', 'Amount', 'Status', 
                  'Razorpay_Order_ID', 'Razorpay_Payment_ID', 'Razorpay_Signature', 'Created_At']
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
                'total_received': total_received,
                'received_count': received_count,
                'refer_help_amount': refer_help_amount,
                'amount_if_paid': refer_help_paid_amount,
                'total_amount_sent': total_amount_sent,
                'total_amount_received': total_amount_received
            })

        return Response(report_data)

# Existing DashboardReportViewSet (unchanged)
class DashboardReportViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminUser]

    def list(self, request):
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

        # Latest report: Data for latest help requests and payment
        latest_refer_help = UserLevel.objects.filter(level__name='Refer Help').order_by('-approved_at').first()
        latest_level_help = UserLevel.objects.filter(level__name__contains='Level').order_by('-approved_at').first()
        latest_level_payment = LevelPayment.objects.order_by('-created_at').first()

        latest_report = {
            'latest_refer_help': latest_refer_help.level.name if latest_refer_help else 'N/A',
            'latest_refer_user': {
                'name': f"{latest_refer_help.user.first_name} {latest_refer_help.user.last_name}".strip() if latest_refer_help else 'N/A',
                'email_id': latest_refer_help.user.email if latest_refer_help else 'N/A',
                'first_name': latest_refer_help.user.first_name if latest_refer_help else 'N/A',
                'last_name': latest_refer_help.user.last_name if latest_refer_help else 'N/A',
                'amount': latest_refer_help.level.amount if latest_refer_help else 0,
                'time': latest_refer_help.approved_at.strftime('%Y-%m-%d %H:%M:%S') if latest_refer_help and latest_refer_help.approved_at else 'N/A'
            } if latest_refer_help else {
                'name': 'N/A', 'email_id': 'N/A', 'first_name': 'N/A', 'last_name': 'N/A', 'amount': 0, 'time': 'N/A'
            },
            'latest_level_help': latest_level_help.level.name if latest_level_help else 'N/A',
            'latest_level_payment': {
                'amount': latest_level_payment.amount if latest_level_payment else 0,
                'time': latest_level_payment.created_at.strftime('%Y-%m-%d %H:%M:%S') if latest_level_payment else 'N/A',
                'done': latest_level_payment.status == 'Verified' if latest_level_payment else False
            } if latest_level_payment else {'amount': 0, 'time': 'N/A', 'done': False}
        }

        data = {
            'total_members': total_members,
            'total_income': total_income,
            'total_active_level_6': active_level_6,
            'new_users_per_level': new_users_per_level,
            'recent_payments': recent_payments,
            'new_user_registrations': new_user_registrations,
            'latest_report': latest_report
        }
        serializer = DashboardReportSerializer(data)
        return Response(serializer.data)

# Existing UserReportViewSet (unchanged)
class UserReportViewSet(viewsets.ViewSet):
    # No permission_classes specified, assumes IsAuthenticated by default or custom logic if needed

    @action(detail=False, methods=['get'], url_path='user-report')
    def user_report(self, request):
        logger.debug("User report endpoint hit for user %s", request.user.user_id)
        user = request.user
        user_levels = UserLevel.objects.filter(user=user)
        completed_levels = user_levels.filter(status='paid', level__order__lte=6).count()
        total_received = user_levels.aggregate(total=Sum('received'))['total'] or 0
        pending_send_count = user_levels.filter(status='pending').count()
        # Corrected aggregation for total_amount_generated using level__amount
        total_amount_generated = user_levels.filter(status='paid').aggregate(total=Sum('level__amount'))['total'] or 0
        send_help = user_levels.filter(level__name__contains='Refer Help').aggregate(total=Sum('level__amount'))['total'] or 0
        receive_help = user_levels.filter(status='paid').count()
        referral_count = CustomUser.objects.filter(sponsor_id=user.user_id).count()
        total_income = total_received  # Total income is the total amount received by the user
        pending_recevie_count = user_levels.filter(status='pending').count()

        data = {
            'username': f"{user.first_name} {user.last_name}".strip() or user.email,
            'level_completed': completed_levels,
            'total_received': total_received,
            'pending_send_count': pending_send_count,
            'total_amount_generated': total_amount_generated,
            'pending_receive_count': pending_recevie_count,
            'total_income': total_income,
            'send_help': send_help,
            'receive_help': receive_help,
            'referral_count': referral_count
        }
        return Response(data)

    @action(detail=False, methods=['get'], url_path='total-payment-info')
    def total_payment_info(self, request):
        user = request.user
        user_levels = UserLevel.objects.filter(user=user)
        total_amount_received = user_levels.aggregate(total=Sum('received'))['total'] or 0
        total_amount_generated = user_levels.filter(status='paid').aggregate(total=Sum('level__amount'))['total'] or 0
        balance_left = total_amount_received - total_amount_generated  # Preliminary calculation

        data = {
            'total_amount_received': total_amount_received,
            'balance_left': max(balance_left, 0)  
        }
        return Response(data)

# Existing UserLatestReportView (unchanged)
class UserLatestReportView(APIView):
    def get(self, request, *args, **kwargs):
        logger.debug("User latest report endpoint hit for user %s", request.user.user_id)
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)

        user = request.user
        # Find users referred by the current user using sponsor_id
        referred_users = CustomUser.objects.filter(sponsor_id=user.user_id)
        user_levels = UserLevel.objects.filter(user__in=[user] + list(referred_users)).order_by('-approved_at')

        latest_refer_help = user_levels.filter(level__name='Refer Help').first()
        latest_level_help = user_levels.filter(level__name__contains='Level').order_by('-approved_at').first()
        latest_level_payment = LevelPayment.objects.filter(user_level__user__in=[user] + list(referred_users)).order_by('-created_at').first()

        latest_report = {
            'latest_refer_help': latest_refer_help.level.name if latest_refer_help else 'N/A',
            'latest_refer_user': {
                'name': f"{latest_refer_help.user.first_name} {latest_refer_help.user.last_name}".strip() if latest_refer_help else '',
                'email_id': latest_refer_help.user.email if latest_refer_help else 'admin@gmail.com',
                'first_name': latest_refer_help.user.first_name if latest_refer_help else '',
                'last_name': latest_refer_help.user.last_name if latest_refer_help else '',
                'amount': latest_refer_help.level.amount if latest_refer_help else 1000.0,
                'time': latest_refer_help.approved_at.strftime('%Y-%m-%d %H:%M:%S') if latest_refer_help and latest_refer_help.approved_at else 'N/A',
                'user_id': latest_refer_help.user.user_id if latest_refer_help else 'N/A'
            } if latest_refer_help else {
                'name': '', 'email_id': 'admin@gmail.com', 'first_name': '', 'last_name': '', 'amount': 1000.0, 'time': 'N/A', 'user_id': 'N/A'
            },
            'latest_level_help': latest_level_help.level.name if latest_level_help else 'Level 2',
            'latest_level_user': {
                'name': f"{latest_level_help.user.first_name} {latest_level_help.user.last_name}".strip() if latest_level_help else '',
                'email_id': latest_level_help.user.email if latest_level_help else 'admin@gmail.com',
                'first_name': latest_level_help.user.first_name if latest_level_help else '',
                'last_name': latest_level_help.user.last_name if latest_level_help else '',
                'amount': latest_level_help.level.amount if latest_level_help else 200.0,
                'time': latest_level_help.approved_at.strftime('%Y-%m-%d %H:%M:%S') if latest_level_help and latest_level_help.approved_at else 'N/A',
                'user_id': latest_level_help.user.user_id if latest_level_help else 'N/A'
            } if latest_level_help else {
                'name': '', 'email_id': 'admin@gmail.com', 'first_name': '', 'last_name': '', 'amount': 200.0, 'time': 'N/A', 'user_id': 'N/A'
            },
            'latest_level_payment': {
                'amount': latest_level_payment.amount if latest_level_payment else 200.0,
                'time': latest_level_payment.created_at.strftime('%Y-%m-%d %H:%M:%S') if latest_level_payment else '2025-09-18 16:15:19'
            } if latest_level_payment else {'amount': 200.0, 'time': '2025-09-18 16:15:19'}
        }

        data = {
            'latest_report': latest_report
        }
        return Response(data, status=status.HTTP_200_OK)

# New Report Views
class SendRequestReport(APIView):
    # permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = UserLevel.objects.select_related('user', 'level').filter(user=request.user).order_by('-approved_at')
        
        # Query params
        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        first_name = request.query_params.get("first_name")
        last_name = request.query_params.get("last_name")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        # Filters
        if email:
            queryset = queryset.filter(user__email__icontains=email.lower())
        if first_name:
            queryset = queryset.filter(user__first_name__icontains=first_name.lower())
        if last_name:
            queryset = queryset.filter(user__last_name__icontains=last_name.lower())
        if status and status.lower() != "all":
            if status.lower() == "completed":
                queryset = queryset.filter(status='paid')  
            elif status.lower() == "pending":
                queryset = queryset.exclude(status='paid')
        if user_id:
            queryset = queryset.filter(user__user_id__iexact=user_id)
        if start_date:
            queryset = queryset.filter(approved_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(approved_at__date__lte=end_date)

        # Search filter
        search = request.query_params.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__user_id__icontains=search) |
                Q(level__name__icontains=search) |
                Q(status__icontains=search)
            )

        # Limit
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        # Export options
        if export == "csv":
            return self.export_csv(queryset, 'send_request_report')
        elif export == "pdf":
            return self.export_pdf(queryset, 'send_request_report')
        elif export == "xlsx":
            return self.export_xlsx(queryset, 'send_request_report')

        serializer = SendRequestReportSerializer(queryset, many=True)
        return Response(serializer.data)

    def export_csv(self, queryset, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['From User', 'Username', 'From Name', 'Amount', 'Status', 'Approved At'])
        serializer = SendRequestReportSerializer(queryset, many=True)
        for data in serializer.data:
            writer.writerow([
                data['from_user'],
                data['username'],
                data['from_name'],
                str(data['amount']),
                data['status'],
                data['approved_at'] if data['approved_at'] else ''
            ])
        return response

    def export_pdf(self, queryset, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').title()} Report", styles["Title"]))

        data = [['From User', 'Username', 'From Name', 'Amount', 'Status', 'Approved At']]
        serializer = SendRequestReportSerializer(queryset, many=True)
        for data_item in serializer.data:
            data.append([
                data_item['from_user'],
                data_item['username'],
                data_item['from_name'],
                str(data_item['amount']),
                data_item['status'],
                data_item['approved_at'] if data_item['approved_at'] else ''
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        response.write(buffer.getvalue())
        buffer.close()
        return response

    def export_xlsx(self, queryset, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "SendRequestReport"
        ws.append(['From User', 'Username', 'From Name', 'Amount', 'Status', 'Approved At'])
        serializer = SendRequestReportSerializer(queryset, many=True)
        for data in serializer.data:
            ws.append([
                data['from_user'],
                data['username'],
                data['from_name'],
                data['amount'],
                data['status'],
                data['approved_at'] if data['approved_at'] else ''
            ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response





class AUCReport(APIView):
    # permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = UserLevel.objects.select_related('user', 'level').filter(user=request.user).order_by('-approved_at')
        
        # Query params
        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        first_name = request.query_params.get("first_name")
        last_name = request.query_params.get("last_name")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        # Filters
        if email:
            queryset = queryset.filter(user__email__icontains=email.lower())
        if first_name:
            queryset = queryset.filter(user__first_name__icontains=first_name.lower())
        if last_name:
            queryset = queryset.filter(user__last_name__icontains=last_name.lower())
        if status and status.lower() != "all":
            if status.lower() == "completed":
                queryset = queryset.filter(status='paid')
            elif status.lower() == "pending":
                queryset = queryset.exclude(status='paid')
        if user_id:
            queryset = queryset.filter(user__user_id__iexact=user_id)
        if start_date:
            queryset = queryset.filter(approved_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(approved_at__date__lte=end_date)

        # Search filter
        search = request.query_params.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__user_id__icontains=search) |
                Q(status__icontains=search)
            )

        # Limit
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        # Export options
        if export == "csv":
            return self.export_csv(queryset, 'auc_report')
        elif export == "pdf":
            return self.export_pdf(queryset, 'auc_report')
        elif export == "xlsx":
            return self.export_xlsx(queryset, 'auc_report')

        serializer = AUCReportSerializer(queryset, many=True)
        return Response(serializer.data)

    def export_csv(self, queryset, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Date'])
        serializer = AUCReportSerializer(queryset, many=True)
        for data in serializer.data:
            writer.writerow([
                data['from_user'],
                data['username'],
                data['from_name'],
                data['linked_username'],
                str(data['amount']),
                data['status'],
                data['date'] if data['date'] else ''
            ])
        return response

    def export_pdf(self, queryset, filename_prefix):
        buffer = io.BytesIO()
        try:
            p = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            y = height - 50
            p.setFont("Helvetica-Bold", 14)
            p.drawString(150, y, f"{filename_prefix.replace('_', ' ').title()} Report")
            y -= 30
            p.setFont("Helvetica", 10)

            # Header
            header = "From User | Username | From Name | Linked Username | Amount | Status | Date"
            p.drawString(50, y, header)
            y -= 20

            # Data
            serializer = AUCReportSerializer(queryset, many=True)
            for data in serializer.data:
                line = f"{data['from_user']} | {data['username']} | {data['from_name']} | {data['linked_username']} | {data['amount']} | {data['status']} | {data['date'] if data['date'] else ''}"
                p.drawString(50, y, line)
                y -= 20
                if y < 50:
                    p.showPage()
                    y = height - 50

            p.save()
            pdf = buffer.getvalue()
            buffer.close()

            response = HttpResponse(pdf, content_type="application/pdf")
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")  # e.g., 20250920_0114
            response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timestamp}.pdf"'
            response['Content-Length'] = len(pdf)
            logger.info(f"PDF exported successfully: {len(queryset)} records processed")
        except Exception as e:
            logger.error(f"Error generating PDF: {e}", exc_info=True)
            return HttpResponse(f"Error generating PDF: {str(e)}", status=500)
        finally:
            if 'buffer' in locals() and buffer:
                buffer.close()
                logger.debug("Buffer closed")

        return response

    def export_xlsx(self, queryset, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "AUCReport"
        ws.append(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Date'])
        serializer = AUCReportSerializer(queryset, many=True)
        for data in serializer.data:
            ws.append([
                data['from_user'],
                data['username'],
                data['from_name'],
                data['linked_username'],
                data['amount'],
                data['status'],
                data['date'] if data['date'] else ''
            ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timestamp}.xlsx"'
        return response



class PaymentReport(APIView):
    # permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = UserLevel.objects.select_related('user', 'level').filter(user=request.user).order_by('-approved_at')
        
        # Query params
        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        first_name = request.query_params.get("first_name")
        last_name = request.query_params.get("last_name")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        # Filters
        if email:
            queryset = queryset.filter(user__email__icontains=email.lower())
        if first_name:
            queryset = queryset.filter(user__first_name__icontains=first_name.lower())
        if last_name:
            queryset = queryset.filter(user__last_name__icontains=last_name.lower())
        if status and status.lower() != "all":
            if status.lower() == "completed":
                queryset = queryset.filter(status='paid')  
            elif status.lower() == "pending":
                queryset = queryset.exclude(status='paid')
        if user_id:
            queryset = queryset.filter(user__user_id__iexact=user_id)
        if start_date:
            queryset = queryset.filter(approved_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(approved_at__date__lte=end_date)

        # Search filter
        search = request.query_params.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__user_id__icontains=search) |
                Q(status__icontains=search)
            )

        # Limit
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        # Export options
        if export == "csv":
            return self.export_csv(queryset, 'payment_report')
        elif export == "pdf":
            return self.export_pdf(queryset, 'payment_report')
        elif export == "xlsx":
            return self.export_xlsx(queryset, 'payment_report')

        serializer = PaymentReportSerializer(queryset, many=True)
        return Response(serializer.data)

    def export_csv(self, queryset, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Payout Amount', 'Transaction Fee', 'Status', 'Approved At', 'Total'])
        serializer = PaymentReportSerializer(queryset, many=True)
        for data in serializer.data:
            writer.writerow([
                data['from_user'],
                data['username'],
                data['from_name'],
                data['linked_username'],
                str(data['amount']),
                str(data['payout_amount']),
                str(data['transaction_fee']),
                data['status'],
                data['approved_at'] if data['approved_at'] else '',
                str(data['total'])
            ])
        return response

    def export_pdf(self, queryset, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').title()} Report", styles["Title"]))

        data = [['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Payout Amount', 'Transaction Fee', 'Status', 'Approved At', 'Total']]
        serializer = PaymentReportSerializer(queryset, many=True)
        for data_item in serializer.data:
            data.append([
                data_item['from_user'],
                data_item['username'],
                data_item['from_name'],
                data_item['linked_username'],
                str(data_item['amount']),
                str(data_item['payout_amount']),
                str(data_item['transaction_fee']),
                data_item['status'],
                data_item['approved_at'] if data_item['approved_at'] else '',
                str(data_item['total'])
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        response.write(buffer.getvalue())
        buffer.close()
        return response

    def export_xlsx(self, queryset, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "PaymentReport"
        ws.append(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Payout Amount', 'Transaction Fee', 'Status', 'Approved At', 'Total'])
        serializer = PaymentReportSerializer(queryset, many=True)
        for data in serializer.data:
            ws.append([
                data['from_user'],
                data['username'],
                data['from_name'],
                data['linked_username'],
                data['amount'],
                data['payout_amount'],
                data['transaction_fee'],
                data['status'],
                data['approved_at'] if data['approved_at'] else '',
                data['total']
            ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response

class BonusSummary(APIView):
    # permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = CustomUser.objects.filter(is_active=True).prefetch_related('userlevel_set')
        
        # Query params
        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        first_name = request.query_params.get("first_name")
        last_name = request.query_params.get("last_name")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        # Filters
        if email:
            queryset = queryset.filter(email__icontains=email.lower())
        if first_name:
            queryset = queryset.filter(first_name__icontains=first_name.lower())
        if last_name:
            queryset = queryset.filter(last_name__icontains=last_name.lower())
        if status and status.lower() != "all":
            if status.lower() == "completed":
                queryset = queryset.filter(status='paid')  
            elif status.lower() == "pending":
                queryset = queryset.exclude(status='paid')
        if user_id:
            queryset = queryset.filter(user_id__iexact=user_id)
        if start_date:
            queryset = queryset.filter(date_of_joining__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date_of_joining__date__lte=end_date)

        # Search filter
        search = request.query_params.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(user_id__icontains=search) |
                Q(email__icontains=search)
            )

        # Limit
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        report_data = []
        for user in queryset:
            user_levels = UserLevel.objects.filter(user=user)
            if user_levels.exists():  # Only include users with levels
                report_data.append({
                    'user': user,
                    'user_levels': user_levels
                })

        # Export options
        if export == "csv":
            return self.export_csv(report_data, 'bonus_summary')
        elif export == "pdf":
            return self.export_pdf(report_data, 'bonus_summary')
        elif export == "xlsx":
            return self.export_xlsx(report_data, 'bonus_summary')

        serializer = BonusSummarySerializer(report_data, many=True)
        return Response(serializer.data)

    def export_csv(self, report_data, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['From User', 'Username', 'From Name', 'Linked Username', 'Bonus Amount', 'Status', 'Approved At', 'Total Bonus'])
        for item in report_data:
            user = item['user']
            user_levels = item['user_levels']
            latest_level = user_levels.order_by('-approved_at').first()
            serializer = BonusSummarySerializer(user_levels, many=True)
            for data in serializer.data:
                writer.writerow([
                    data['from_user'],
                    data['username'],
                    data['from_name'],
                    data['linked_username'],
                    str(data['bonus_amount']),
                    data['status'],
                    data['approved_at'] if data['approved_at'] else '',
                    str(data['total_bonus'])
                ])
        return response

    def export_pdf(self, report_data, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').title()} Report", styles["Title"]))

        data = [['From User', 'Username', 'From Name', 'Linked Username', 'Bonus Amount', 'Status', 'Approved At', 'Total Bonus']]
        for item in report_data:
            user = item['user']
            user_levels = item['user_levels']
            latest_level = user_levels.order_by('-approved_at').first()
            serializer = BonusSummarySerializer(user_levels, many=True)
            for data_item in serializer.data:
                data.append([
                    data_item['from_user'],
                    data_item['username'],
                    data_item['from_name'],
                    data_item['linked_username'],
                    str(data_item['bonus_amount']),
                    data_item['status'],
                    data_item['approved_at'] if data_item['approved_at'] else '',
                    str(data_item['total_bonus'])
                ])

        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        response.write(buffer.getvalue())
        buffer.close()
        return response

    def export_xlsx(self, report_data, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "BonusSummary"
        ws.append(['From User', 'Username', 'From Name', 'Linked Username', 'Bonus Amount', 'Status', 'Approved At', 'Total Bonus'])
        for item in report_data:
            user = item['user']
            user_levels = item['user_levels']
            latest_level = user_levels.order_by('-approved_at').first()
            serializer = BonusSummarySerializer(user_levels, many=True)
            for data in serializer.data:
                ws.append([
                    data['from_user'],
                    data['username'],
                    data['from_name'],
                    data['linked_username'],
                    data['bonus_amount'],
                    data['status'],
                    data['approved_at'] if data['approved_at'] else '',
                    data['total_bonus']
                ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response

class LevelUsersReport(APIView):
    # permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = UserLevel.objects.select_related('user', 'level').filter(user=request.user).order_by('-approved_at')
        
        # Query params
        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        first_name = request.query_params.get("first_name")
        last_name = request.query_params.get("last_name")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        # Filters
        if email:
            queryset = queryset.filter(user__email__icontains=email.lower())
        if first_name:
            queryset = queryset.filter(user__first_name__icontains=first_name.lower())
        if last_name:
            queryset = queryset.filter(user__last_name__icontains=last_name.lower())
        if status and status.lower() != "all":
            if status.lower() == "completed":
                queryset = queryset.filter(status='paid')  
            elif status.lower() == "pending":
                queryset = queryset.exclude(status='paid')
        if user_id:
            queryset = queryset.filter(user__user_id__iexact=user_id)
        if start_date:
            queryset = queryset.filter(approved_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(approved_at__date__lte=end_date)

        # Search filter
        search = request.query_params.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__user_id__icontains=search) |
                Q(level__name__icontains=search) |
                Q(status__icontains=search)
            )

        # Limit
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        # Export options
        if export == "csv":
            return self.export_csv(queryset, 'level_users_report')
        elif export == "pdf":
            return self.export_pdf(queryset, 'level_users_report')
        elif export == "xlsx":
            return self.export_xlsx(queryset, 'level_users_report')

        serializer = LevelUsersSerializer(queryset, many=True)
        return Response(serializer.data)

    def export_csv(self, queryset, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Level', 'Approved At', 'Total'])
        serializer = LevelUsersSerializer(queryset, many=True)
        for data in serializer.data:
            writer.writerow([
                data['from_user'],
                data['username'],
                data['from_name'],
                data['linked_username'],
                str(data['amount']),
                data['status'],
                data['level'],
                data['approved_at'] if data['approved_at'] else '',
                str(data['total'])
            ])
        return response

    def export_pdf(self, queryset, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').title()} Report", styles["Title"]))

        data = [['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Level', 'Approved At', 'Total']]
        serializer = LevelUsersSerializer(queryset, many=True)
        for data_item in serializer.data:
            data.append([
                data_item['from_user'],
                data_item['username'],
                data_item['from_name'],
                data_item['linked_username'],
                str(data_item['amount']),
                data_item['status'],
                data_item['level'],
                data_item['approved_at'] if data_item['approved_at'] else '',
                str(data_item['total'])
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        response.write(buffer.getvalue())
        buffer.close()
        return response

    def export_xlsx(self, queryset, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "LevelUsersReport"
        ws.append(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Level', 'Approved At', 'Total'])
        serializer = LevelUsersSerializer(queryset, many=True)
        for data in serializer.data:
            ws.append([
                data['from_user'],
                data['username'],
                data['from_name'],
                data['linked_username'],
                data['amount'],
                data['status'],
                data['level'],
                data['approved_at'] if data['approved_at'] else '',
                data['total']
            ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response