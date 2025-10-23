from io import BytesIO
import csv
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from django.http import HttpResponse

from users.models import CustomUser

import logging
from django.conf import settings

logger = logging.getLogger(__name__)

import os
import random
import string
import json
import urllib.request
import traceback
from django.utils import timezone
from datetime import timedelta

# def assign_placement_id(sponsor):
#     if not sponsor:
#         return None

#     # Get all users already placed under this sponsor
#     placed_children = CustomUser.objects.filter(placement_id=sponsor.user_id).order_by("id")

#     if placed_children.count() < 2:  # Only first 2 get placement
#         return sponsor.user_id
#     return None  # Others get no placement

# def generate_next_placementid():
#     """
#     Generate next placement_id for a new user.
#     For now, it just increments the max existing placement_id by 1.
#     """
    

#     last_user = CustomUser.objects.order_by("-placement_id").first()
#     if last_user and last_user.placement_id:
#         try:
#             return int(last_user.placement_id) + 1
#         except ValueError:
#             return 1
#     return 1


def validate_sponsor(sponsor_id: str) -> bool:
    if not sponsor_id:
        return True
    return CustomUser.objects.filter(user_id=sponsor_id).exists()

def export_users_csv(queryset, filename="users.csv", user_levels=None):
    if user_levels is None:
        user_levels = {}

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(["Name", "User ID", "Level", "Profile Image", "Status"])

    for user in queryset:
        profile = getattr(user, "profile", None)
        profile_img = getattr(profile, "profile_image", None) if profile else None
        profile_url = profile_img.url if profile_img else ""
        if len(profile_url) > 50:
            profile_url = profile_url[:47] + "..."
        full_name = f"{user.first_name} {user.last_name}".strip() or user.user_id
        level = user_levels.get(user.user_id, "")
        # writer.writerow([full_name, user.user_id, getattr(user, "level", ""), profile_url, "Active" if user.is_active else "Blocked"])
        writer.writerow([full_name, user.user_id, level, profile_url, "Active" if user.is_active else "Blocked"])

    return response

def export_users_pdf(queryset, filename="users.pdf", title="Users Report", user_levels=None):
    if user_levels is None:
        user_levels = {}

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph(title, styles["Title"]))

    # ✅ Import safe level calculator
    # try:
    #     from .views import compute_user_levels
    #     user_levels = compute_user_levels()
    # except Exception:
    #     user_levels = {}

    # Table header
    data = [["Name", "User ID", "Level", "Profile Image", "Status"]]

    for user in queryset:
        # try:
        #     # Safe profile access
        #     profile = getattr(user, "profile", None)
        #     profile_img = getattr(profile, "profile_image", None) if profile else None
        #     profile_url = getattr(profile_img, "url", "") if profile_img else ""

        #     # Trim long URLs for PDF layout
        #     if profile_url and len(profile_url) > 50:
        #         profile_url = profile_url[:47] + "..."

        #     full_name = (f"{user.first_name} {user.last_name}".strip() or user.user_id)
        #     status = "Active" if getattr(user, "is_active", False) else "Blocked"

        #     # ✅ Use precomputed level (fallback to empty string)
        #     level = user_levels.get(user.user_id, "")

        #     data.append([full_name, user.user_id, str(level), profile_url, status])
        # except Exception as e:
        #     # In case any single row breaks, push a safe fallback row
        #     data.append([str(user), getattr(user, "user_id", ""), "", "", "ERROR"])
        profile = getattr(user, "profile", None)
        profile_img = getattr(profile, "profile_image", None) if profile else None
        profile_url = getattr(profile_img, "url", "") if profile_img else ""
        if profile_url and len(profile_url) > 50:
            profile_url = profile_url[:47] + "..."
        full_name = f"{user.first_name} {user.last_name}".strip() or user.user_id
        level = user_levels.get(user.user_id, "")
        status = "Active" if getattr(user, "is_active", False) else "Blocked"
        data.append([full_name, user.user_id, str(level), profile_url, status])

    # Create table
    table = Table(data, colWidths=[150, 70, 50, 150, 60])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ]))

    elements.append(table)
    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(pdf)
    return response


from decimal import Decimal
from django.db.models import Sum
from level.models import UserLevel 
from users.models import CustomUser 


def check_child_creation_eligibility(user):
    """
    Determines if a user is eligible to create a new child 
    and whether any milestone notification should be triggered.
    """

    # Calculate total received income
    total_received = (
        UserLevel.objects.filter(user=user)
        .aggregate(total=Sum('received'))
        .get('total') or Decimal('0.00')
    )

    # Count existing children
    child_count = CustomUser.objects.filter(parent=user).count()

    # Define caps and maximum children
    caps = [Decimal('10000'), Decimal('20000'), Decimal('25000'), Decimal('35000')]
    max_children = len(caps)

    # If already reached max children
    if child_count >= max_children:
        return {
            "eligible": False,
            "message": f"Maximum limit of {max_children} child users already created.",
            "notification": None
        }

    next_child_number = child_count + 1
    cap_amount = caps[child_count]

    # Eligibility check
    if total_received >= cap_amount:
        notification = f"🎉 You have reached ₹{cap_amount}! Eligible to create child #{next_child_number}."
        return {
            "eligible": True,
            "message": f"Eligible to create child #{next_child_number}.",
            "notification": notification
        }
    else:
        required = cap_amount - total_received
        return {
            "eligible": False,
            "message": f"Earn ₹{required} more to unlock child #{next_child_number} creation.",
            "notification": None  # No notification yet
        }

