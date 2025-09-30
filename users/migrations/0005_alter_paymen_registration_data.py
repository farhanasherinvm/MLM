# users/migrations/XXXX_fix_bad_registration_data.py
from django.db import migrations
import json

def clean_bad_registration_data(apps, schema_editor):
    Payment = apps.get_model("users", "Payment")
    for payment in Payment.objects.all():
        raw = payment.registration_data
        if not raw:
            continue
        try:
            json.loads(raw)
        except Exception:
            # Overwrite invalid JSON with empty dict
            payment.registration_data = "{}"
            payment.save(update_fields=["registration_data"])

class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_alter_customuser_sponsor_id"),
    ]

    operations = [
        migrations.RunPython(clean_bad_registration_data),
    ]
