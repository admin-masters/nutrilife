from django.contrib import admin
from .models import Screening

@admin.register(Screening)
class ScreeningAdmin(admin.ModelAdmin):
    list_display = ("student", "organization", "risk_level", "screened_at")
    list_filter = ("organization", "risk_level", "screened_at")
    search_fields = ("student__first_name", "student__last_name")
