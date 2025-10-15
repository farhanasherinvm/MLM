
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from .models import Level 
from django.db import transaction

@receiver(post_migrate)
def create_initial_levels(sender, **kwargs):
    # Ensure this runs only for the 'level' app
    if sender.name == 'level': 
        

        try:
            # Check if levels already exist to prevent unnecessary transaction overhead
            if not Level.objects.exists():
                with transaction.atomic():
                    Level.create_default_levels()
                    print("✅ Initial MLM Levels successfully created via post_migrate.")
                
        except Exception as e:
            print(f"❌ Failed to set up initial levels: {e}")

