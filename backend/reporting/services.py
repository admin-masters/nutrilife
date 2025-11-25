from __future__ import annotations
from datetime import datetime, timedelta, date
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from accounts.models import Organization
from screening.models import Screening
from assist.models import Application
from program.models import Enrollment, MonthlySupply, ComplianceSubmission, ScreeningMilestone
from .models import SchoolStatDaily, SchoolReportStatus

def _bounds_for_day(day: date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    end = timezone.make_aware(datetime.combine(day, datetime.max.time()), tz)
    return start, end

@transaction.atomic
def build_daily_rollup(org: Organization, day: date) -> SchoolStatDaily:
    start, end = _bounds_for_day(day)

    # Screenings
    screenings = Screening.objects.filter(organization=org, screened_at__range=(start, end))
    screened = screenings.count()
    red_flags = screenings.filter(risk_level="RED").count()

    # Applications by timestamps
    applied = Application.objects.filter(organization=org, applied_at__range=(start, end)).count()
    forwarded = Application.objects.filter(organization=org, forwarded_at__range=(start, end)).count()
    approved = Application.objects.filter(organization=org, sapa_reviewed_at__range=(start, end), status="APPROVED").count()
    rejected = Application.objects.filter(organization=org, sapa_reviewed_at__range=(start, end), status="REJECTED").count()

    # Enrollments created today
    enrollments_created = Enrollment.objects.filter(organization=org, created_at__range=(start, end)).count()

    # Logistics
    supplies_delivered = MonthlySupply.objects.filter(enrollment__organization=org, delivered_on=day).count()

    # Compliance
    comps = ComplianceSubmission.objects.filter(monthly_supply__enrollment__organization=org, submitted_at__range=(start, end))
    compliance_submitted = comps.count()
    compliance_compliant = comps.filter(status="COMPLIANT").count()
    compliance_unable = comps.filter(status="UNABLE").count()

    # Milestones (events on this day)
    milestones_due = ScreeningMilestone.objects.filter(enrollment__organization=org, due_on=day).count()
    milestones_overdue = ScreeningMilestone.objects.filter(enrollment__organization=org, status="OVERDUE", updated_at__range=(start, end)).count()
    milestones_completed = ScreeningMilestone.objects.filter(enrollment__organization=org, status="COMPLETED", completed_at__range=(start, end)).count()

    # Upsert
    SchoolStatDaily.objects.filter(organization=org, day=day).delete()
    row = SchoolStatDaily.objects.create(
        organization=org, day=day,
        screened=screened, red_flags=red_flags,
        applied=applied, forwarded=forwarded, approved=approved, rejected=rejected,
        enrollments_created=enrollments_created,
        supplies_delivered=supplies_delivered,
        compliance_submitted=compliance_submitted, compliance_compliant=compliance_compliant, compliance_unable=compliance_unable,
        milestones_due=milestones_due, milestones_overdue=milestones_overdue, milestones_completed=milestones_completed,
    )
    # ensure report status row exists
    rs, _ = SchoolReportStatus.objects.get_or_create(organization=org)
    rs.ensure_defaults()
    return row

def build_rollups_for_day(day: date) -> int:
    n = 0
    for org in Organization.objects.all().iterator():
        build_daily_rollup(org, day)
        n += 1
    return n

def period_summary(org: Organization, start_day: date, end_day: date) -> dict:
    qs = SchoolStatDaily.objects.filter(organization=org, day__gte=start_day, day__lte=end_day)
    agg = {
        "screened": 0, "red_flags": 0,
        "applied": 0, "forwarded": 0, "approved": 0, "rejected": 0,
        "enrollments_created": 0,
        "supplies_delivered": 0,
        "compliance_submitted": 0, "compliance_compliant": 0, "compliance_unable": 0,
        "milestones_due": 0, "milestones_overdue": 0, "milestones_completed": 0,
    }
    for r in qs:
        for k in agg.keys():
            agg[k] += getattr(r, k, 0)
    # convenience metrics
    agg["compliance_rate"] = round((agg["compliance_compliant"] / agg["compliance_submitted"]) * 100, 1) if agg["compliance_submitted"] else 0.0
    agg["red_rate"] = round((agg["red_flags"] / agg["screened"]) * 100, 1) if agg["screened"] else 0.0
    return agg

def six_month_window_ending(day: date):
    start = day - timedelta(days=180)
    return start, day
