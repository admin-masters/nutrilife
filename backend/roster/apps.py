from django.apps import AppConfig


class RosterConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'roster'
    def ready(self):
        # Register signal handlers that seed default classrooms for new schools.
        from . import signals  # noqa: F401
