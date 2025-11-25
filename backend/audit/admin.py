from django.contrib import admin
from .models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organization", "actor", "action", "target_model", "target_id")
    list_filter = ("organization", "action")
    search_fields = ("target_id", "actor__email", "organization__name")
