import json
import logging
from django.core.management.base import BaseCommand
from users.models import Payment

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Scan all Payment rows and repair corrupted registration_data JSON."

    def handle(self, *args, **options):
        fixed_count = 0
        skipped_count = 0

        for payment in Payment.objects.all():
            raw = payment.registration_data
            if not raw:
                skipped_count += 1
                continue

            try:
                json.loads(raw)  # test if valid JSON
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"Payment {payment.id} has invalid JSON. Resetting to {{}}. Error: {e}"
                    )
                )
                logger.warning(
                    f"Invalid registration_data JSON for Payment {payment.id}: {e}"
                )
                payment.registration_data = "{}"
                payment.save(update_fields=["registration_data"])
                fixed_count += 1
            else:
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Repair complete. Fixed {fixed_count} corrupted rows, skipped {skipped_count} valid rows."
            )
        )
