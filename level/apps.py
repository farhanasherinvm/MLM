
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class LevelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'level'

    def ready(self):
        # IMPORTANT: Imports must be inside ready() to avoid startup errors
        from .models import Level 
        from django.db import transaction
        from django.db.utils import ProgrammingError
        from decimal import Decimal

        # This block prevents crashes if the database table hasn't been created yet (e.g., during the initial 'migrate')
        try:
            # Check if the Level table exists. Using introspection is a more robust check.
            all_models = list(self.get_models())

            if all_models and Level._meta.db_table not in all_models[0]._meta.db_connection.introspection.table_names():
                return
        except ProgrammingError:
            # Catch exceptions that occur if the database connection isn't fully ready
            return

        # Core logic to create the levels if they don't exist
        try:
            # Call your existing class method to create the levels
            # You must ensure the Decimal conversion is correct if your create_default_levels 
            # doesn't handle it, or just use the Decimal casting inside your models.py method.
            with transaction.atomic():
                Level.create_default_levels()
        except Exception as e:
            # Log the error but don't crash the entire server startup process
            logger.error(f"❌ Failed to set up initial levels on startup: {e}")