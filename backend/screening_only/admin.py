from django.contrib import admin
from .models import ScreeningSchoolProfile, ScreeningTermsAcceptance


@admin.register(ScreeningSchoolProfile)
class ScreeningSchoolProfileAdmin(admin.ModelAdmin):
    list_display = ("organization", "district", "principal_email", "operator_email", "created_at")
    search_fields = ("organization__name", "principal_email", "operator_email", "district")


@admin.register(ScreeningTermsAcceptance)
class ScreeningTermsAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "actor_role", "version", "accepted_at")
    search_fields = ("organization__name", "user__email", "actor_role", "version")
