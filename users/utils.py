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

import random
import string
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

def _send_via_django(subject, message, recipient_list, from_email=None, fail_silently=True):
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=fail_silently,
        )
        return True, None
    except Exception as e:
        logger.warning("Django send_mail failed: %s", e)
        return False, f"Django send_mail failed: {e}"

def _send_via_smtplib(subject, message, recipient_list, from_email=None):
    """
    Low-level SMTP fallback using smtplib. Uses settings.EMAIL_* credentials.
    This may fail if the host blocks outbound SMTP.
    """
    try:
        import smtplib
        from email.mime.text import MIMEText

        smtp_host = getattr(settings, "EMAIL_HOST", "smtp.gmail.com")
        smtp_port = getattr(settings, "EMAIL_PORT", 587)
        use_tls = getattr(settings, "EMAIL_USE_TLS", True)
        username = getattr(settings, "EMAIL_HOST_USER", None)
        password = getattr(settings, "EMAIL_HOST_PASSWORD", None)
        from_addr = from_email or username or ("no-reply@" + (settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "example.com"))
        to_addr_list = recipient_list if isinstance(recipient_list, (list, tuple)) else [recipient_list]

        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addr_list)

        server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
        if use_tls:
            server.starttls()
        if username and password:
            server.login(username, password)
        server.sendmail(from_addr, to_addr_list, msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        logger.warning("smtplib send failed: %s", e)
        return False, f"smtplib send failed: {e}"

def _send_via_sendgrid_http(subject, message, recipient_list, from_email=None):
    """
    HTTP fallback using SendGrid Web API. Requires settings.SENDGRID_API_KEY.
    If you want to use SendGrid, set SENDGRID_API_KEY in your settings (or environment).
    """
    api_key = getattr(settings, "SENDGRID_API_KEY", None)
    if not api_key:
        return False, "SendGrid API key not configured."
    try:
        import json
        import urllib.request

        url = "https://api.sendgrid.com/v3/mail/send"
        data = {
            "personalizations": [{"to": [{"email": email} for email in (recipient_list if isinstance(recipient_list, (list,tuple)) else [recipient_list])]}],
            "from": {"email": from_email or settings.DEFAULT_FROM_EMAIL},
            "subject": subject,
            "content": [{"type": "text/plain", "value": message}],
        }
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            if 200 <= resp.getcode() < 300:
                return True, None
            else:
                return False, f"SendGrid returned status {resp.getcode()}"
    except Exception as e:
        logger.warning("SendGrid HTTP send failed: %s", e)
        return False, f"SendGrid HTTP send failed: {e}"

def safe_send_mail(subject, message, recipient_list, from_email=None, fail_silently=True):
    """
    Always try HTTP API first (SendGrid). SMTP will almost always fail on Render.
    """
    # 1) Try SendGrid API
    sent, err = _send_via_sendgrid_http(subject, message, recipient_list, from_email)
    if sent:
        return True, None

    # 2) Fallback to Django send_mail (SMTP)
    sent2, err2 = _send_via_django(subject, message, recipient_list, from_email, fail_silently)
    if sent2:
        return True, None

    # 3) Fallback to smtplib (last resort)
    sent3, err3 = _send_via_smtplib(subject, message, recipient_list, from_email)
    if sent3:
        return True, None

    return False, "; ".join(filter(None, [err, err2, err3]))

    
def generate_numeric_otp(length=None):
    """Generate numeric OTP string. Length uses settings.OTP_LENGTH or defaults to 6."""
    length = length or getattr(settings, "OTP_LENGTH", 6)
    return "".join(random.choices(string.digits, k=int(length)))

def create_and_send_otp(email):
    """
    Create an EmailVerification entry with an OTP and send it to the user's email.
    Returns tuple: (EmailVerification instance, sent_boolean, error_message_or_None)
    """
    email = email.strip().lower()
    otp = generate_numeric_otp()
    expiry_minutes = getattr(settings, "OTP_EXPIRY_MINUTES", 10)

    ev = EmailVerification.objects.create(
        email=email,
        otp_code=otp,
        expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
        is_verified=False,
        attempts=0
    )

    subject = "Your verification code"
    message = (
        f"Your verification code is: {otp}\n\n"
        f"This code expires in {expiry_minutes} minute(s).\n\n"
        "If you didn't request this, please ignore this email."
    )
    sent, error = safe_send_mail(subject=subject, message=message, recipient_list=[email])
    if sent:
        logger.info("Sent OTP email to %s (db id=%s)", email, ev.id)
        return ev, True, None
    else:
        logger.warning("Failed to send OTP email for %s (db id=%s): %s", email, ev.id, error)
        # We still return the ev object so the flow can continue, but indicate sending failed.
        return ev, False, error