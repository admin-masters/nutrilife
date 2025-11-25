from django.contrib import admin
from .models import Enrollment
from django.contrib import admin
from django.utils import timezone
from .models import Enrollment, MonthlySupply
from .models import ComplianceSubmission
from .models import ScreeningMilestone

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("organization","student","status","start_date","end_date","approved_by")
    list_filter = ("organization","status")
    search_fields = ("student__first_name","student__last_name")

@admin.action(description="Mark as delivered today (sets compliance due +27 days)")
def _mark_delivered_today(modeladmin, request, queryset):
    from .services import mark_supply_delivered
    for s in queryset:
        mark_supply_delivered(s, timezone.now().date(), actor=request.user)

@admin.register(MonthlySupply)
class MonthlySupplyAdmin(admin.ModelAdmin):
    list_display = ("enrollment","month_index","scheduled_delivery_date","delivered_on","compliance_due_at","qr_token")
    list_filter = ("enrollment__organization","delivered_on")
    search_fields = ("enrollment__student__first_name","enrollment__student__last_name","qr_token")
    actions = [_mark_delivered_today]

@admin.register(ComplianceSubmission)
class ComplianceSubmissionAdmin(admin.ModelAdmin):
    list_display = ("monthly_supply","status","submitted_at")
    list_filter = ("status","monthly_supply__enrollment__organization")
    search_fields = ("monthly_supply__enrollment__student__first_name",
                     "monthly_supply__enrollment__student__last_name")

@admin.register(ScreeningMilestone)
class ScreeningMilestoneAdmin(admin.ModelAdmin):
    list_display = ("enrollment","milestone","status","due_on","completed_at")
    list_filter = ("status","milestone","enrollment__organization")
    search_fields = ("enrollment__student__first_name","enrollment__student__last_name")
