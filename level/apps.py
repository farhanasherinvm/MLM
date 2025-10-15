from django.apps import AppConfig

class LevelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'level'

    def ready(self):
        # ⚠️ Import the signals file here to register the post_migrate handler
        import level.signals 