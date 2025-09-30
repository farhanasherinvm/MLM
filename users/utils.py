from io import BytesIO
import csv
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from django.http import HttpResponse

from users.models import CustomUser, EmailVerification

import logging
from django.core.mail import send_mail
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

def assign_placement_id(sponsor):
    if not sponsor:
        return None

    # Get all users already placed under this sponsor
    placed_children = CustomUser.objects.filter(placement_id=sponsor.user_id).order_by("id")

    if placed_children.count() < 2:  # Only first 2 get placement
        return sponsor.user_id
    return None  # Others get no placement

def generate_next_placementid():
    """
    Generate next placement_id for a new user.
    For now, it just increments the max existing placement_id by 1.
    """
    

    last_user = CustomUser.objects.order_by("-placement_id").first()
    if last_user and last_user.placement_id:
        try:
            return int(last_user.placement_id) + 1
        except ValueError:
            return 1
    return 1


def validate_sponsor(sponsor_id: str) -> bool:
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

def _send_via_sendgrid(subject, message, recipient_list, from_email=None):
    api_key = getattr(settings, "SENDGRID_API_KEY", None)
    if not api_key:
        return False, "SendGrid API key not configured"
    try:
        url = "https://api.sendgrid.com/v3/mail/send"
        data = {
            "personalizations": [{"to": [{"email": e} for e in (recipient_list if isinstance(recipient_list, (list, tuple)) else [recipient_list])]}],
            "from": {"email": from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")},
            "subject": subject,
            "content": [{"type": "text/plain", "value": message}],
        }
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.getcode()
            if 200 <= status < 300:
                return True, None
            return False, f"SendGrid returned HTTP {status}"
    except Exception as e:
        logger.warning("SendGrid send failed: %s", e)
        return False, f"SendGrid exception: {e}"

def _send_via_django(subject, message, recipient_list, from_email=None):
    try:
        send_mail(subject, message, from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None), recipient_list)
        return True, None
    except Exception as e:
        logger.warning("Django send_mail failed: %s", e)
        return False, f"Django send_mail exception: {e}"

def _send_via_smtplib(subject, message, recipient_list, from_email=None):
    try:
        import smtplib
        from email.mime.text import MIMEText
        smtp_host = getattr(settings, "EMAIL_HOST", "smtp.gmail.com")
        smtp_port = getattr(settings, "EMAIL_PORT", 587)
        use_tls = getattr(settings, "EMAIL_USE_TLS", True)
        username = getattr(settings, "EMAIL_HOST_USER", None)
        password = getattr(settings, "EMAIL_HOST_PASSWORD", None)
        from_addr = from_email or username or ("no-reply@" + (settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "example.com"))
        to_addrs = recipient_list if isinstance(recipient_list, (list, tuple)) else [recipient_list]
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
        if use_tls:
            server.starttls()
        if username and password:
            server.login(username, password)
        server.sendmail(from_addr, to_addrs, msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        logger.warning("smtplib send failed: %s", e)
        return False, f"smtplib exception: {e}"

def safe_send_mail(subject, message, recipient_list, from_email=None):
    sent, err = _send_via_sendgrid(subject, message, recipient_list, from_email)
    if sent: return True, None
    sent, err2 = _send_via_django(subject, message, recipient_list, from_email)
    if sent: return True, None
    sent, err3 = _send_via_smtplib(subject, message, recipient_list, from_email)
    if sent: return True, None
    errors = "; ".join(filter(None, [err, err2 if 'err2' in locals() else None, err3 if 'err3' in locals() else None]))
    return False, errors or "All send attempts failed"

def generate_numeric_otp(length=None):
    length = int(length or getattr(settings, "OTP_LENGTH", 6))
    return "".join(random.choices(string.digits, k=length))

def create_and_send_otp(email):
    """
    Create an EmailVerification entry with an OTP.
    Try sending, but ALWAYS return the OTP in provider_info if running on Render.
    """
    try:
        email_clean = email.strip().lower()
        otp = generate_numeric_otp()
        expiry_minutes = int(getattr(settings, "OTP_EXPIRY_MINUTES", 10))

        ev = EmailVerification.objects.create(
            email=email_clean,
            otp_code=otp,
            expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
            is_verified=False,
            attempts=0,
        )

        subject = "Your verification code"
        message = f"Your verification code is: {otp}\n\nThis code expires in {expiry_minutes} minute(s)."

        sent, error = safe_send_mail(subject, message, [email_clean], getattr(settings, "DEFAULT_FROM_EMAIL", None))

        # ✅ Always expose OTP in provider_info if running on Render
        if os.environ.get("RENDER"):
            provider_info = {
                "transport": "render-fallback",
                "detail": "SMTP/email may be blocked on Render. OTP included in response for testing.",
                "otp": otp,
            }
            return ev, True, None, provider_info

        if sent:
            return ev, True, None, {"transport": "normal", "detail": "Email accepted by backend"}
        else:
            return ev, False, error, {"transport": "normal", "detail": error, "otp": otp}

    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("Unexpected error in create_and_send_otp")
        try:
            return ev, False, str(e), {"traceback": tb, "otp": otp}
        except NameError:
            return None, False, str(e), {"traceback": tb}