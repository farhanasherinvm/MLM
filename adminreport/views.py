from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from django.db.models import Q, Sum, Count, F,IntegerField, DecimalField
from django.utils import timezone
from level.models import UserLevel, LevelPayment,Level
from users.models import CustomUser
from .models import AdminNotification
from .serializers import (
    AUCReportSerializer,
    AdminNotificationSerializer,
    AdminSendRequestReportSerializer,
    AdminPaymentSerializer,
    AdminSummaryAnalyticsSerializer,
    UserAnalyticsSerializer
) # Only import the specific serializers
from django.http import HttpResponse
import csv
import io
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from openpyxl import Workbook
import logging
from rest_framework.generics import ListAPIView
from rest_framework import status
from decimal import Decimal
from django.db.utils import OperationalError, ProgrammingError
from django.core.exceptions import FieldError
from django.db.models.expressions import OuterRef, Subquery 
from users.models import Payment
from level.models import PmfPayment
from operator import attrgetter
logger = logging.getLogger(__name__)

# Helper function for safe date conversion (used in both views)
def safe_parse_date(date_str):
    try:
        return timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None



class AdminAUCReportView(APIView):
    permission_classes = [IsAdminUser]
    pagination_class = PageNumberPagination
    pagination_class.page_size = 10
    
    def get_all_payment_data(self):
        # 1. Fetch Registration Payments (must be Verified)
        registration_payments = Payment.objects.filter(
            status='Verified' 
        ).select_related('user').all()

        # 2. Fetch PMF Payments (must be Verified)
        pmf_payments = PmfPayment.objects.filter(
            status='Verified'
        ).select_related('user').all()

        # Combine and sort by creation date (descending)
        combined_data = sorted(
            list(registration_payments) + list(pmf_payments),
            key=attrgetter('created_at'),
            reverse=True
        )
        return combined_data

    def apply_filters(self, request, combined_data):
        

        email = request.query_params.get("email", '').lower()
        user_id = request.query_params.get("user_id", '').lower()
        search = request.query_params.get('search', '').lower()
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        
        start_date = safe_parse_date(start_date_str)
        end_date = safe_parse_date(end_date_str)
        
        filtered_data = []

        for item in combined_data:
            # Need to re-implement the user retrieval utility here if it's not a method on the view
            def _get_user_from_item(obj):
                if hasattr(obj, 'user') and obj.user:
                    return obj.user
                
                if obj.__class__.__name__ == 'Payment':
                    payment_user_id = getattr(obj, 'user_id', None)
                    
                    if payment_user_id:
                        try:
                            return CustomUser.objects.get(user_id=payment_user_id)
                        except CustomUser.DoesNotExist:
                            pass
                            
                return None
            
            user = _get_user_from_item(item)

            if user is None:
                continue 
            
            # --- Text/ID Filters ---
            match_text = True
            if search or user_id or email:
                user_match = False
                if user:
                    if user_id and user.user_id.lower() == user_id:
                        user_match = True
                    elif email and user.email and user.email.lower().find(email) != -1:
                        user_match = True
                    elif search:
                        name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".lower()
                        if user.user_id.lower().find(search) != -1 or name.find(search) != -1 or (user.email and user.email.lower().find(search) != -1):
                            user_match = True
                
                if (user_id or email or search) and not user_match:
                    match_text = False

            # --- Date Filters ---
            match_date = True
            item_date = item.created_at.date() if item.created_at else None
            
            if item_date:
                if start_date and item_date < start_date:
                    match_date = False
                if end_date and item_date > end_date:
                    match_date = False
            else:
                if start_date or end_date:
                    match_date = False

            if match_text and match_date:
                filtered_data.append(item)

            if limit:
                try:
                    limit_int = int(limit)
                    filtered_data = filtered_data[:limit_int]
                    # If we're exporting, we use this limited set.
                except ValueError:
                    pass 

        return filtered_data


    def get(self, request):
        combined_data = self.get_all_payment_data()
        
        # 1. Apply Filters
        filtered_data = self.apply_filters(request, combined_data)
        
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")
        
        # 2. Handle Limit
        if limit:
            try:
                limit_int = int(limit)
                queryset_for_export = filtered_data[:limit_int]
                # If we're exporting, we use this limited set.
            except ValueError:
                pass 

                

        # 3. Serialize all filtered data to calculate totals, regardless of pagination/limit
        full_serialized_data = AUCReportSerializer(filtered_data, many=True).data

        # 4. Calculate Total Payments and GST
        total_payments = sum(Decimal(item['amount']) for item in full_serialized_data)
        total_gst = sum(Decimal(item['gst_total']) for item in full_serialized_data)
        total_cgst = sum(Decimal(item['cgst']) for item in full_serialized_data)
        total_sgst = sum(Decimal(item['sgst']) for item in full_serialized_data)
        
        totals = {
            'total_payments': total_payments.quantize(Decimal('0.01')),
            'total_gst': total_gst.quantize(Decimal('0.01')),
            'total_cgst': total_cgst.quantize(Decimal('0.01')),
            'total_sgst': total_sgst.quantize(Decimal('0.01')),
        }

        # 5. Handle Export
        if export in ["csv", "pdf", "xlsx"]:
            # Use the filtered_data for export
            if export == "csv":
                return self.export_csv(filtered_data, totals, 'auc_report')
            elif export == "pdf":
                return self.export_pdf(filtered_data, totals, 'auc_report')
            # elif export == "xlsx":
            #     return self.export_xlsx(filtered_data, totals, 'auc_report') 

        # 6. Handle Pagination (for JSON response)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(filtered_data, request)
        
        if page is not None:
            serializer = AUCReportSerializer(page, many=True)
            response_data = paginator.get_paginated_response(serializer.data).data
            # Add totals to the paginated response
            response_data['report_totals'] = totals
            return Response(response_data)
            
        # If no pagination/limit, return all data + totals
        return Response({
            'results': full_serialized_data,
            'report_totals': totals
        })

    # --- Export Methods (Updated to include totals) ---

    def export_csv(self, queryset, totals, filename_prefix):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        
        writer.writerow(['User ID', 'Name', 'Phone', 'Email', 'Type', 'Amount', 'Status', 'Date', 'GST Total', 'CGST', 'SGST'])
        
        serializer = AUCReportSerializer(queryset, many=True)
        for data in serializer.data:
            writer.writerow([
                data['user_id'], data['user_name'], data['phone_number'], data['email'], 
                data['transaction_type'], str(data['amount']), data['status'], 
                str(data['date']) if data['date'] else '', 
                str(data['gst_total']), str(data['cgst']), str(data['sgst'])
            ])
            
        # Add totals section
        writer.writerow([])
        writer.writerow(['TOTALS:', '', '', '', '', ''])
        writer.writerow(['Total Payments', str(totals['total_payments'])])
        writer.writerow(['Total GST', str(totals['total_gst'])])
        writer.writerow(['Total CGST', str(totals['total_cgst'])])
        writer.writerow(['Total SGST', str(totals['total_sgst'])])
        
        return response

    def export_pdf(self, queryset, totals, filename_prefix):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30)
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"{filename_prefix.replace('_', ' ').upper()} REPORT", styles["Title"]))
        elements.append(Spacer(1, 12))

        # --- Data Table ---
        data = [['User ID', 'Name', 'Phone', 'Email', 'Type', 'Amount', 'Status', 'Date', 'GST Total', 'CGST', 'SGST']]
        
        serializer = AUCReportSerializer(queryset, many=True)
        for data_item in serializer.data:
            data.append([
                data_item['user_id'], data_item['user_name'], data_item['phone_number'], data_item['email'], 
                data_item['transaction_type'], str(data_item['amount']), data_item['status'], 
                str(data_item['date']) if data_item['date'] else '', 
                str(data_item['gst_total']), str(data_item['cgst']), str(data_item['sgst'])
            ])

        table_width = A4[0] - 60 
        col_widths = [table_width * w for w in [0.09, 0.15, 0.11, 0.17, 0.11, 0.08, 0.08, 0.10, 0.11, 0.09, 0.09]]
        table = Table(data, colWidths=col_widths)
        
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#CCCCCC')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (5, 1), (10, -1), 'RIGHT'), # Align amounts to the right
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 24))
        
        # --- Totals Table ---
        totals_data = [
            ['Report Totals', ''],
            ['Total Payments', f"₹ {totals['total_payments']}"],
            ['Total GST (18%)', f"₹ {totals['total_gst']}"],
            ['Total CGST (9%)', f"₹ {totals['total_cgst']}"],
            ['Total SGST (9%)', f"₹ {totals['total_sgst']}"],
        ]
        
        totals_table = Table(totals_data, colWidths=[2.5*inch, 1.5*inch])
        totals_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(totals_table)

        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
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





class AdminAnalyticsView(APIView):
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        # Default behavior: Return summary or user_stats based on query param
        report_type = request.query_params.get('report', 'summary').lower()
        
        try:
            if report_type == 'summary':
                return self._get_summary_analytics(request)
            elif report_type == 'user_stats':
                return self._get_user_statistics(request)
            
            return Response({"detail": "Invalid report type specified. Use 'summary' or 'user_stats'."}, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            print(f"Critical error in AdminAnalyticsView GET: {e}")
            return Response({"detail": "An unexpected server error occurred during report generation."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def _get_summary_analytics(self, request):
            try:
                # 1. Total Users
                total_registered_users = CustomUser.objects.count()
                total_active_users = CustomUser.objects.filter(is_active=True).count()
                
                # 2. Total Revenue & GIC (Aggregating from AdminNotification)
                notification_stats = AdminNotification.objects.filter(
                    operation_type='level_payment'
                ).aggregate(
                    total_revenue_notified=Sum('amount'),
                    total_gic_collected=Sum('gic')
                )

                total_revenue_paid = notification_stats['total_revenue_notified'] or Decimal('0.00')
                total_gic_collected = notification_stats['total_gic_collected'] or Decimal('0.00')

                # --- 👇 ADD NEW CALCULATION HERE 👇 ---
                
                # Calculate Total Income Received from ALL paid UserLevel entries
                income_stats = UserLevel.objects.filter(
                    status='paid'
                ).aggregate(
                    total_income_received_sum=Sum('received')
                )
                total_received_income = income_stats['total_income_received_sum'] or Decimal('0.00')

                # --- 👆 END NEW CALCULATION 👆 ---
                
                # 3. Users by Level (UserLevel to Level via FK)
                users_per_level = UserLevel.objects.filter(
                    status='paid',
                    level__isnull=False
                ).values(
                    'level__name', 'level__order'
                ).annotate(
                    # Count the distinct users associated with these paid level entries
                    count=Count('user_id', distinct=True) 
                ).order_by('level__order')

                # Convert the queryset result into a dictionary for easy look-up
                # This dictionary now correctly maps 'Level Name' to 'Total Unique Users who own it'
                users_by_level_dict = {
                    item['level__name']: item['count'] 
                    for item in users_per_level if item.get('level__name')
                }
                
                data = {
                    'total_registered_users': total_registered_users,
                    'total_active_users': total_active_users,
                    'total_revenue_paid': total_revenue_paid.quantize(Decimal('0.01')),
                    'total_gic_collected': total_gic_collected.quantize(Decimal('0.01')),
                    
                    # --- 👇 ADD TO DATA DICTIONARY HERE 👇 ---
                    'total_received_income': total_received_income.quantize(Decimal('0.01')),
                    # --- 👆 END ADDITION 👆 ---
                    
                    'Completed_users_by_level': users_by_level_dict,
                }
                
                # FIX: Must explicitly use 'data=' keyword
                serializer = AdminSummaryAnalyticsSerializer(data=data) 
                serializer.is_valid(raise_exception=True) 
                return Response(serializer.data)

            except (FieldError, OperationalError, ProgrammingError) as e:
                error_msg = "Database/Model configuration error while calculating summary analytics. "
                print(f"{error_msg} Details: {e}")
                return Response({"detail": error_msg, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Exception as e:
                print(f"Unexpected error in _get_summary_analytics: {e}")
                return Response({"detail": "An unexpected error occurred in summary calculation."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _get_user_statistics(self, request):
        try:
            # 1. Base Query: All users
            queryset = CustomUser.objects.all().order_by('user_id')
            
            # **FIXED REFERRALS**: Subquery for CharField sponsor_id
            referral_count_subquery = CustomUser.objects.filter(
                sponsor_id=OuterRef('user_id')
            ).values('sponsor_id').annotate(
                count=Count('id')
            ).values('count')[:1] 
            
            placement_count_subquery = CustomUser.objects.filter(
                    placement_id=OuterRef('user_id')
                ).values('placement_id').annotate(
                    count=Count('id')
                ).values('count')[:1]
            # 2. Add Annotations
            queryset = queryset.annotate(
                # FIX: Explicit output_field=models.IntegerField()
                total_referrals=Subquery(referral_count_subquery, output_field=IntegerField()), 
                current_level_placement_count=Subquery(placement_count_subquery, output_field=IntegerField()),
                
                # Income: Aggregating 'received' from UserLevel
                total_income_generated=Sum(
                    'userlevel__received',
                    # Ensure the output type is correct for decimal data
                    output_field=DecimalField(max_digits=12, decimal_places=2) 
                ),

                # Levels Completed: Counting paid UserLevel records
                levels_completed=Count(
                    'userlevel',
                    filter=Q(userlevel__status='paid'),
                    distinct=True
                ),
                
                # Payments Made: user -> userlevel -> payments -> amount
                total_payments_made=Sum(
                    'userlevel__payments__amount',
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            ).prefetch_related('userlevel_set__level') # Prefetch for the loop

            user_id_search = request.query_params.get('user_id')
            if user_id_search:
                # Use 'icontains' for case-insensitive partial match, or 'exact' if you only want perfect matches
                queryset = queryset.filter(user_id__icontains=user_id_search)

            # Filter by levels_completed (exact match)
            levels_completed_filter = request.query_params.get('levels_completed')
            if levels_completed_filter:
                try:
                    # Filter against the 'levels_completed' annotation
                    queryset = queryset.filter(levels_completed=int(levels_completed_filter))
                except ValueError:
                    return Response(
                        {"detail": "Invalid levels_completed parameter. Must be an integer."}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # 3. Pagination
            paginator = PageNumberPagination()
            limit_param = request.query_params.get('limit')
            
            if limit_param:
                try:
                    paginator.page_size = int(limit_param) # Set page_size to the requested limit
                except ValueError:
                    return Response(
                        {"detail": "Invalid limit parameter. Must be an integer."}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                paginator.page_size = 10
            page = paginator.paginate_queryset(queryset, request)
            
            data = []
            for user in page:
                # --- SAFE CURRENT LEVEL LOGIC ---
                active_level_entry = user.userlevel_set.all().filter(
                    status='paid' 
                ).order_by('-level__order').first() 
                
                full_name_candidate = f"{user.first_name} {user.last_name}".strip()
    
                # 2. Check if the constructed name is blank and fall back to user_id or username
                final_full_name = full_name_candidate or user.first_name or user.user_id 
                    
                data.append({
                    'user_id': user.user_id,
                    'full_name': final_full_name,
                    'total_income_generated': user.total_income_generated or Decimal('0.00'),
                    'total_referrals': user.total_referrals or 0,
                    'current_level': user.current_level_placement_count or 0,
                    'levels_completed': user.levels_completed or 0,
                    'total_payments_made': user.total_payments_made or Decimal('0.00'),
                    
                })

            # FIX: Must explicitly use 'data=' keyword
            serializer = UserAnalyticsSerializer(data=data, many=True)
            serializer.is_valid(raise_exception=True) 
            return paginator.get_paginated_response(serializer.data)

        except (FieldError, OperationalError, ProgrammingError) as e:
            error_msg = "Database/Model configuration error while generating user statistics. Check annotation field names."
            print(f"{error_msg} Details: {e}")
            return Response({"detail": error_msg, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            error = (f"Unexpected error in _get_user_statistics: {e}")
            return Response({"detail": error}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)