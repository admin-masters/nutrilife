from django.apps import AppConfig

class ReportingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reporting"

    def ready(self):
        # Register signal handlers that keep SchoolStatDaily rollups up-to-date.
        from . import signals  # noqa: F401