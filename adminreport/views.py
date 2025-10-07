from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from django.db.models import Q, Sum
from django.utils import timezone
from level.models import UserLevel, LevelPayment
from users.models import CustomUser
from .models import AdminNotification
from .serializers import (
    AUCReportSerializer,
    AdminNotificationSerializer,
    AdminSendRequestReportSerializer,
    AdminPaymentSerializer,
) # Only import the specific serializers
from django.http import HttpResponse
import csv
import io
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from openpyxl import Workbook
import logging
from rest_framework.generics import ListAPIView


logger = logging.getLogger(__name__)

# Helper function for safe date conversion (used in both views)
def safe_parse_date(date_str):
    try:
        return timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

# --- Existing AUC Report View (Kept as is for compatibility with combined data) ---

class AdminAUCReportView(APIView):
    permission_classes = [IsAdminUser]
    pagination_class = PageNumberPagination
    pagination_class.page_size = 10

    def get(self, request):
        user_levels = UserLevel.objects.select_related('user', 'level').all()
        level_payments = LevelPayment.objects.select_related('user_level__user', 'user_level__level').all()
        auc_data = list(user_levels) + list(level_payments)

        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        username = request.query_params.get("username")
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")
        
        start_date = safe_parse_date(start_date_str)
        end_date = safe_parse_date(end_date_str)

        # Filters - (Object list filtering is retained from original AUC View)
        if email:
            auc_data = [item for item in auc_data if hasattr(item, 'user') and getattr(item.user, 'email', '').lower().find(email.lower()) != -1]
        
        if username:
            auc_data = [item for item in auc_data if hasattr(item, 'user') and (
                getattr(item.user, 'first_name', '').lower().find(username.lower()) != -1 or
                getattr(item.user, 'last_name', '').lower().find(username.lower()) != -1 or
                f"{getattr(item.user, 'first_name', '')} {getattr(item.user, 'last_name', '')}".lower().find(username.lower()) != -1
            )]
            
        if status and status.lower() != "all":
            if status.lower() == "completed":
                auc_data = [item for item in auc_data if getattr(item, 'status', '').lower() == 'paid']
            elif status.lower() == "pending":
                auc_data = [item for item in auc_data if getattr(item, 'status', '').lower() != 'paid']
                
        if user_id:
            auc_data = [item for item in auc_data if hasattr(item, 'user') and getattr(item.user, 'user_id', '').lower() == user_id.lower()]
            
        if start_date:
            auc_data = [item for item in auc_data if (
                (getattr(item, 'requested_date', None) and item.requested_date.date() >= start_date) or
                (getattr(item, 'created_at', None) and item.created_at.date() >= start_date)
            )]
        if end_date:
            auc_data = [item for item in auc_data if (
                (getattr(item, 'requested_date', None) and item.requested_date.date() <= end_date) or
                (getattr(item, 'created_at', None) and item.created_at.date() <= end_date)
            )]

        search = request.query_params.get('search', '')
        if search:
            auc_data = [item for item in auc_data if (
                hasattr(item, 'user') and (
                    getattr(item.user, 'first_name', '').lower().find(search.lower()) != -1 or
                    getattr(item.user, 'last_name', '').lower().find(search.lower()) != -1 or
                    getattr(item.user, 'user_id', '').lower().find(search.lower()) != -1 or
                    (getattr(item, 'status', '') and item.status.lower().find(search.lower()) != -1) or
                    (getattr(item, 'payment_method', '') and item.payment_method.lower().find(search.lower()) != -1)
                )
            )]

        if limit:
            try:
                limit = int(limit)
                auc_data = auc_data[:limit]
            except ValueError:
                pass

        # Export options (Re-used helper methods from original code)
        if export == "csv":
            return self.export_csv(auc_data, 'auc_report')
        elif export == "pdf":
            return self.export_pdf(auc_data, 'auc_report')
        elif export == "xlsx":
            return self.export_xlsx(auc_data, 'auc_report')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(auc_data, request)
        if page is not None:
            serializer = AUCReportSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
            
        serializer = AUCReportSerializer(auc_data, many=True, context={'request': request})
        return Response(serializer.data)

    # Export methods for AUCReportView (Re-used from original code)
    def export_csv(self, queryset, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Date', 'Payment Method'])
        serializer = AUCReportSerializer(queryset, many=True)
        for data in serializer.data:
            writer.writerow([
                data['from_user'], data['username'], data['from_name'], data['linked_username'], str(data['amount']), 
                data['status'], str(data['date']) if data['date'] else '', data['payment_method']
            ])
        return response

    def export_pdf(self, queryset, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').title()} Report", styles["Title"]))

        data = [['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Date', 'Payment Method']]
        serializer = AUCReportSerializer(queryset, many=True)
        for data_item in serializer.data:
            data.append([
                data_item['from_user'], data_item['username'], data_item['from_name'], data_item['linked_username'], 
                str(data_item['amount']), data_item['status'], str(data_item['date']) if data_item['date'] else '', data_item['payment_method']
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        return response

    def export_xlsx(self, queryset, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "AUCReport"
        ws.append(['From User', 'Username', 'From Name', 'Linked Username', 'Amount', 'Status', 'Date', 'Payment Method'])
        serializer = AUCReportSerializer(queryset, many=True)
        for data in serializer.data:
            ws.append([
                data['from_user'], data['username'], data['from_name'], data['linked_username'], 
                data['amount'], data['status'], str(data['date']) if data['date'] else '', data['payment_method']
            ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(output, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response

# ----------------------------------------------------------------------------
# --- NEW SPECIFIC REPORT VIEWS (Replacing AllAdminReportsView logic) ---
# ----------------------------------------------------------------------------

class AdminSendRequestView(APIView):
    permission_classes = [IsAdminUser]
    pagination_class = PageNumberPagination
    pagination_class.page_size = 10

    def get(self, request):
        queryset = UserLevel.objects.select_related('user', 'level').prefetch_related('payments').all().order_by('-requested_date')

        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        username = request.query_params.get("username")
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")
        search = request.query_params.get('search', '')
        
        start_date = safe_parse_date(start_date_str)
        end_date = safe_parse_date(end_date_str)

        q_objects = Q()
        if email:
            q_objects &= Q(user__email__icontains=email)
        if user_id:
            q_objects &= Q(user__user_id__iexact=user_id)
        if username:
            q_objects &= (Q(user__first_name__icontains=username) | Q(user__last_name__icontains=username))
        
        if status and status.lower() != "all":
            if status.lower() == "completed":
                q_objects &= Q(status='paid')
            elif status.lower() == "pending":
                q_objects &= ~Q(status='paid')
        
        if search:
            q_objects &= (
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__user_id__icontains=search) |
                Q(status__icontains=search)
            )

        queryset = queryset.filter(q_objects)
        
        if start_date:
            queryset = queryset.filter(requested_date__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(requested_date__date__lte=end_date)
            
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass
        
        if export:
            export_data = AdminSendRequestReportSerializer(queryset, many=True, context={'request': request}).data
            if export == "csv":
                return self._export_csv_send_request(export_data, 'send_request_report')
            elif export == "pdf":
                return self._export_pdf_send_request(export_data, 'send_request_report')
            elif export == "xlsx":
                return self._export_xlsx_send_request(export_data, 'send_request_report')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        
        serializer = AdminSendRequestReportSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def _export_csv_send_request(self, data, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'From User', 'Username', 'From Name', 'Amount', 'Status', 'Requested Date', 'Payment Method', 'Level', 'Linked Username'])
        
        for item in data:
            writer.writerow([
                item['id'], item['from_user'], item['username'], item['from_name'], str(item['amount']),
                item['status'], str(item['requested_date']) if item['requested_date'] else '',
                item['payment_method'], item['level'], item['linked_username']
            ])
        return response

    def _export_pdf_send_request(self, data, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').title()} Report", styles["Title"]))

        table_data = [['ID', 'From User', 'Username', 'From Name', 'Amount', 'Status', 'Requested Date', 'Payment Method', 'Level', 'Linked Username']]
        for item in data:
            table_data.append([
                str(item['id']), item['from_user'], item['username'], item['from_name'], str(item['amount']),
                item['status'], str(item['requested_date']) if item['requested_date'] else '',
                item['payment_method'], item['level'], item['linked_username']
            ])
        
        table = Table(table_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        return response
    
    def _export_xlsx_send_request(self, data, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "SendRequestReport"
        ws.append(['ID', 'From User', 'Username', 'From Name', 'Amount', 'Status', 'Requested Date', 'Payment Method', 'Level', 'Linked Username'])
        for item in data:
            ws.append([
                item['id'], item['from_user'], item['username'], item['from_name'], item['amount'],
                item['status'], str(item['requested_date']) if item['requested_date'] else '',
                item['payment_method'], item['level'], item['linked_username']
            ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(output, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response

class AdminPaymentReportView(APIView):
    permission_classes = [IsAdminUser]
    pagination_class = PageNumberPagination
    pagination_class.page_size = 10

    def get(self, request):
        queryset = LevelPayment.objects.select_related('user_level__user', 'user_level__level').all().order_by('-created_at')

        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        username = request.query_params.get("username")
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")
        search = request.query_params.get('search', '')

        start_date = safe_parse_date(start_date_str)
        end_date = safe_parse_date(end_date_str)

        q_objects = Q()
        if email:
            q_objects &= Q(user_level__user__email__icontains=email)
        if user_id:
            q_objects &= Q(user_level__user__user_id__iexact=user_id)
        if username:
            q_objects &= (Q(user_level__user__first_name__icontains=username) | Q(user_level__user__last_name__icontains=username))
        
        if status and status.lower() != "all":
            q_objects &= Q(status__iexact=status)
        
        if search:
            q_objects &= (
                Q(user_level__user__first_name__icontains=search) |
                Q(user_level__user__last_name__icontains=search) |
                Q(user_level__user__user_id__icontains=search) |
                Q(status__icontains=search) |
                Q(payment_method__icontains=search)
            )

        queryset = queryset.filter(q_objects)
        
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
            
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        if export:
            export_data = AdminPaymentSerializer(queryset, many=True).data
            if export == "csv":
                return self._export_csv_payment(export_data, 'payment_report')
            elif export == "pdf":
                return self._export_pdf_payment(export_data, 'payment_report')
            elif export == "xlsx":
                return self._export_xlsx_payment(export_data, 'payment_report')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        
        serializer = AdminPaymentSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def _export_csv_payment(self, data, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        
        writer.writerow(['ID', 'From User', 'Username', 'Linked Username', 'Level', 'Amount', 'GIC', 'Status', 'Payment Method', 'Created At'])
        
        for item in data:
            writer.writerow([
                item['id'], item['from_user'], item['username'], item['linked_username'], 
                item['level'], str(item['amount']), str(item['gic']), item['status'], 
                item['payment_method'], str(item['created_at'])
            ])
        return response

    def _export_pdf_payment(self, data, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').title()} Report", styles["Title"]))

        table_data = [['ID', 'From User', 'Username', 'Linked Username', 'Level', 'Amount', 'GIC', 'Status', 'Payment Method', 'Created At']]
        for item in data:
            table_data.append([
                str(item['id']), item['from_user'], item['username'], item['linked_username'], 
                item['level'], str(item['amount']), str(item['gic']), item['status'], 
                item['payment_method'], str(item['created_at'])
            ])
        
        table = Table(table_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        return response
    
    def _export_xlsx_payment(self, data, filename_prefix):
        wb = Workbook()
        ws = wb.active
        ws.title = "PaymentReport"
        ws.append(['ID', 'From User', 'Username', 'Linked Username', 'Level', 'Amount', 'GIC', 'Status', 'Payment Method', 'Created At'])
        for item in data:
            ws.append([
                item['id'], item['from_user'], item['username'], item['linked_username'], 
                item['level'], item['amount'], item['gic'], item['status'], 
                item['payment_method'], str(item['created_at'])
            ])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(output, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response

class AdminNotificationsView(ListAPIView):
    queryset = AdminNotification.objects.all().order_by('-timestamp')
    # Use the individual model serializer here
    serializer_class = AdminNotificationSerializer 
    permission_classes = [IsAdminUser]
    pagination_class = PageNumberPagination