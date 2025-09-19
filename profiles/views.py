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

        
        email = request.query_params.get("email")
        status = request.query_params.get("status")
        user_id = request.query_params.get("user_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit")
        export = request.query_params.get("export")  # 'csv', 'pdf', 'xlsx'

        
        if email:
            all_referrals = [r for r in all_referrals if email.lower() in r.email.lower()]

        if status and status.lower() != "all":
            if status.lower() == "active":
                all_referrals = [r for r in all_referrals if r.is_active]
            elif status.lower() == "inactive":
                all_referrals = [r for r in all_referrals if not r.is_active]

        if user_id:
            all_referrals = [r for r in all_referrals if str(r.user_id) == str(user_id)]

        if start_date:
            start_date_parsed = parse_date(start_date)
            if start_date_parsed:
                all_referrals = [
                    r for r in all_referrals
                    if r.date_of_joining and r.date_of_joining.date() >= start_date_parsed
                ]

        if end_date:
            end_date_parsed = parse_date(end_date)
            if end_date_parsed:
                all_referrals = [
                    r for r in all_referrals
                    if r.date_of_joining and r.date_of_joining.date() <= end_date_parsed
                ]

        #  Sort by joining date 
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

        # CSV Export 
        if export == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="referrals.csv"'
            writer = csv.writer(response)
            writer.writerow(["User ID", "Email", "Status", "Date of Joining"])
            for r in all_referrals:
                writer.writerow([
                    r.user_id,
                    r.email,
                    "Active" if r.is_active else "Inactive",
                    r.date_of_joining.strftime("%Y-%m-%d") if r.date_of_joining else "",
                ])
            return response

        #  PDF Export 
        elif export == "pdf":
            buffer = BytesIO()
            p = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            y = height - 50
            p.setFont("Helvetica-Bold", 14)
            p.drawString(200, y, "Referral List")
            y -= 30
            p.setFont("Helvetica", 10)
            for r in all_referrals:
                line = f"{r.user_id} | {r.email} | {'Active' if r.is_active else 'Inactive'} | {r.date_of_joining.strftime('%Y-%m-%d') if r.date_of_joining else ''}"
                p.drawString(50, y, line)
                y -= 20
                if y < 50:
                    p.showPage()
                    y = height - 50
            p.save()
            pdf = buffer.getvalue()
            buffer.close()
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = 'attachment; filename="referrals.pdf"'
            return response

        #  XLSX Export 
        elif export == "xlsx":
            wb = Workbook()
            ws = wb.active
            ws.title = "Referrals"
            ws.append(["User ID", "Email", "Status", "Date of Joining"])

            for r in all_referrals:
                ws.append([
                    r.user_id,
                    r.email,
                    "Active" if r.is_active else "Inactive",
                    r.date_of_joining.strftime("%Y-%m-%d") if r.date_of_joining else "",
                ])

            output = BytesIO()
            wb.save(output)
            output.seek(0)

            response = HttpResponse(
                output,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = 'attachment; filename="referrals.xlsx"'
            return response

        # Default JSON 
        serializer = ReferralListSerializer(all_referrals, many=True)
        return Response(serializer.data)




class AdminHomeView(APIView):
    permission_classes = [IsAdminUser]  
    def get(self, request):
        total_users = CustomUser.objects.count()

        data = {
            "total_users": total_users,
        }
        return Response(data)



