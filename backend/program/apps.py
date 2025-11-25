from django.apps import AppConfig
class ProgramConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "program"
    def ready(self):
        # Import signals so Django registers the receivers at startup
        from . import signals  # noqa 
