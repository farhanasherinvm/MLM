from io import BytesIO
import csv
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from django.http import HttpResponse

from users.models import CustomUser

def validate_sponsor(sponsor_id: str) -> bool:
    """
    Validate sponsor:
      1. Sponsor must exist in the system.
    """
    try:
        sponsor = CustomUser.objects.get(user_id=sponsor_id)
    except CustomUser.DoesNotExist:
        return False

    return CustomUser.objects.filter(user_id=sponsor_id).exists()

def export_users_csv(queryset, filename="users.csv"):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(["Name", "User ID", "Level", "Profile Image", "Status"])

    for user in queryset:
        profile_img = getattr(user.profile, "profile_image", None)
        profile_url = profile_img.url if profile_img else ""
        if len(profile_url) > 50:
            profile_url = profile_url[:47] + "..."
        full_name = f"{user.first_name} {user.last_name}".strip() or user.user_id
        writer.writerow([full_name, user.user_id, user.level, profile_url, "Active" if user.is_active else "Blocked"])

    return response


def export_users_pdf(queryset, filename="users.pdf", title="Users Report"):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph(title, styles["Title"]))

    data = [["Name", "User ID", "Level", "Profile Image", "Status"]]
    for user in queryset:
        profile_img = getattr(user.profile, "profile_image", None)
        profile_url = profile_img.url if profile_img else ""
        if len(profile_url) > 50:
            profile_url = profile_url[:47] + "..."
        full_name = f"{user.first_name} {user.last_name}".strip() or user.user_id
        status = "Active" if user.is_active else "Blocked"
        data.append([full_name, user.user_id, user.level, profile_url, status])

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