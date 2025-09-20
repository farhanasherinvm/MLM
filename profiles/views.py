from rest_framework import generics, permissions
from .models import Profile
from .serializers import ProfileSerializer
from rest_framework.response import Response
from .models import KYC
from .serializers import KYCSerializer
from rest_framework.views import APIView
from .serializers import ReferralSerializer
from django.db.models import Q
from django.contrib.auth import get_user_model

from rest_framework.permissions import IsAuthenticated

from .serializers import ReferralListSerializer
from .utils import get_all_referrals
from rest_framework.permissions import IsAdminUser
from django.utils.dateparse import parse_date

from django.utils.timezone import make_aware, is_naive
from datetime import datetime
from django.http import HttpResponse
import csv
from io import BytesIO
from datetime import datetime
from django.utils.timezone import is_naive, make_aware

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4


CustomUser = get_user_model()





class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Fetch profile of currently logged-in user
        return self.request.user.profile



class KYCView(generics.RetrieveUpdateAPIView):
    serializer_class = KYCSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        #only one KYC
        obj, created = KYC.objects.get_or_create(user=self.request.user)
        return obj

class ReferralView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        referral_id = user.user_id  

        serializer = ReferralSerializer(data={"referral_id": referral_id})
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data)

class ReferralListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        all_referrals = get_all_referrals(user, max_level=6)

        # Query params
        status = request.query_params.get("status")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        # Status filter
        if status and status.lower() != "all":
            if status.lower() == "active":
                all_referrals = [r for r in all_referrals if r.is_active]
            elif status.lower() == "inactive":
                all_referrals = [r for r in all_referrals if not r.is_active]

        # Sort by joining date
        def get_joined_date(u):
            if u.date_of_joining:
                dt = u.date_of_joining
                if is_naive(dt):
                    dt = make_aware(dt)
                return dt
            return datetime.min.replace(tzinfo=None)

        all_referrals.sort(key=get_joined_date, reverse=True)

        if limit:
            try:
                limit = int(limit)
                all_referrals = all_referrals[:limit]
            except ValueError:
                pass

        # Serializer for computed fields
        serializer = ReferralListSerializer(all_referrals, many=True)

        # Prepare data rows with only required fields
        data_rows = []
        for r in serializer.data:
            full_name = r.get('fullname', f"{r.get('first_name','')} {r.get('last_name','')}".strip())
            data_rows.append([
                r.get('user_id', ''),
                full_name,
                r.get('email', ''),
                r.get('mobile', ''),
                r.get('joined_date', ''),
                r.get('total_count', 0),   # referral count
                r.get('level', ''),        # rank/level
                r.get('status', ''),
            ])

        # Column headings
        headings = ["User ID", "Full Name", "Email", "Mobile", "Date of Joining", "Referral Count", "Rank", "Status"]

        # CSV Export
        if export == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="referrals_export.csv"'
            writer = csv.writer(response)
            writer.writerow(headings)
            writer.writerows(data_rows)
            return response

        # PDF Export
        elif export == "pdf":
            buffer = BytesIO()
            p = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            y = height - 50
            p.setFont("Helvetica-Bold", 14)
            p.drawString(150, y, "Referral Export")
            y -= 30

            p.setFont("Helvetica-Bold", 10)
            p.drawString(50, y, " | ".join(headings))
            y -= 20
            p.setFont("Helvetica", 10)

            for row in data_rows:
                line = " | ".join(str(item) for item in row)
                p.drawString(50, y, line)
                y -= 20
                if y < 50:
                    p.showPage()
                    y = height - 50
                    p.setFont("Helvetica-Bold", 10)
                    p.drawString(50, y, " | ".join(headings))
                    y -= 20
                    p.setFont("Helvetica", 10)

            p.save()
            pdf = buffer.getvalue()
            buffer.close()
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = 'attachment; filename="referrals_export.pdf"'
            return response

        # XLSX Export
        elif export == "xlsx":
            wb = Workbook()
            ws = wb.active
            ws.title = "Referrals Export"
            ws.append(headings)
            for row in data_rows:
                ws.append(row)
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            response = HttpResponse(
                output,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = 'attachment; filename="referrals_export.xlsx"'
            return response

        # Default JSON
        return Response(serializer.data)



class AdminHomeView(APIView):
    permission_classes = [IsAdminUser]  
    def get(self, request):
        total_users = CustomUser.objects.count()

        data = {
            "total_users": total_users,
        }
        return Response(data)




class ReferralExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        all_referrals = get_all_referrals(user, max_level=6)

        # Query params
        status = request.query_params.get("status")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        # Status filter
        if status and status.lower() != "all":
            if status.lower() == "active":
                all_referrals = [r for r in all_referrals if r.is_active]
            elif status.lower() == "inactive":
                all_referrals = [r for r in all_referrals if not r.is_active]

        # Sort by joining date
        def get_joined_date(u):
            if u.date_of_joining:
                dt = u.date_of_joining
                if is_naive(dt):
                    dt = make_aware(dt)
                return dt
            return datetime.min.replace(tzinfo=None)

        all_referrals.sort(key=get_joined_date, reverse=True)

        if limit:
            try:
                limit = int(limit)
                all_referrals = all_referrals[:limit]
            except ValueError:
                pass

        # Serializer to get computed fields
        serializer = ReferralListSerializer(all_referrals, many=True)
        data_rows = []
        for r in serializer.data:
            full_name = r.get('fullname', f"{r.get('first_name','')} {r.get('last_name','')}".strip())
            data_rows.append([
                full_name,
                r.get('email', ''),
                r.get('mobile', ''),
                r.get('user_id', ''),
                r.get('position', ''),
                r.get('referred_by_name', ''),
                r.get('joined_date', ''),
                r.get('status', ''),
            ])

        # CSV Export
        if export == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="referrals_export.csv"'
            writer = csv.writer(response)
            writer.writerow(["Full Name", "Email", "Mobile", "User ID", "Position", "Referred By", "Joining Date", "Status"])
            writer.writerows(data_rows)
            return response

        # PDF Export with headings
        elif export == "pdf":
            buffer = BytesIO()
            p = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            y = height - 50
            p.setFont("Helvetica-Bold", 14)
            p.drawString(150, y, "Referral Export")
            y -= 30

            # Column headings
            p.setFont("Helvetica-Bold", 10)
            headings = ["Full Name", "Email", "Mobile", "User ID", "Placement ID", "Sponsor Name", "Joining Date", "Status"]
            p.drawString(50, y, " | ".join(headings))
            y -= 20
            p.setFont("Helvetica", 10)

            for row in data_rows:
                line = " | ".join(str(item) for item in row)
                p.drawString(50, y, line)
                y -= 20
                if y < 50:
                    p.showPage()
                    y = height - 50
                    # Repeat headings on new page
                    p.setFont("Helvetica-Bold", 10)
                    p.drawString(50, y, " | ".join(headings))
                    y -= 20
                    p.setFont("Helvetica", 10)

            p.save()
            pdf = buffer.getvalue()
            buffer.close()
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = 'attachment; filename="referrals_export.pdf"'
            return response

        # XLSX Export
        elif export == "xlsx":
            wb = Workbook()
            ws = wb.active
            ws.title = "Referrals Export"
            ws.append(["Full Name", "Email", "Mobile", "User ID", "Placement ID", "Sponsor Name", "Joining Date", "Status"])
            for row in data_rows:
                ws.append(row)
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            response = HttpResponse(
                output,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = 'attachment; filename="referrals_export.xlsx"'
            return response

        # Default JSON
        return Response(serializer.data)