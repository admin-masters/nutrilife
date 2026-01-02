from __future__ import annotations
from datetime import datetime, timedelta, date
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Count
from django.db.models.functions import TruncDate
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
def _bounds_for_period(start_day: date, end_day: date):
    """Timezone-aware datetime bounds for an inclusive date range."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(start_day, datetime.min.time()), tz)
    end = timezone.make_aware(datetime.combine(end_day, datetime.max.time()), tz)
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

@transaction.atomic
def build_rollups_for_period_bulk(org: Organization, start_day: date, end_day: date) -> int:
    """Build rollups for an org/date range using grouped DB aggregates.

    This is significantly faster than calling build_daily_rollup(...) once per day
    when (re)building large windows like the default 180 days.

    Returns:
      Number of daily rows written.
    """
    if start_day > end_day:
        return 0

    tz = timezone.get_current_timezone()
    start_dt, end_dt = _bounds_for_period(start_day, end_day)

    days: list[date] = []
    d = start_day
    while d <= end_day:
        days.append(d)
        d += timedelta(days=1)

    metrics = {
        "screened": 0,
        "red_flags": 0,
        "applied": 0,
        "forwarded": 0,
        "approved": 0,
        "rejected": 0,
        "enrollments_created": 0,
        "supplies_delivered": 0,
        "compliance_submitted": 0,
        "compliance_compliant": 0,
        "compliance_unable": 0,
        "milestones_due": 0,
        "milestones_overdue": 0,
        "milestones_completed": 0,
    }
    by_day: dict[date, dict] = {day: dict(metrics) for day in days}

    # Screenings
    for r in (
        Screening.objects.filter(organization=org, screened_at__range=(start_dt, end_dt))
        .annotate(day=TruncDate("screened_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["screened"] = r["c"]

    for r in (
        Screening.objects.filter(organization=org, risk_level="RED", screened_at__range=(start_dt, end_dt))
        .annotate(day=TruncDate("screened_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["red_flags"] = r["c"]

    # Applications
    for r in (
        Application.objects.filter(organization=org, applied_at__range=(start_dt, end_dt))
        .annotate(day=TruncDate("applied_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["applied"] = r["c"]

    for r in (
        Application.objects.filter(organization=org, forwarded_at__range=(start_dt, end_dt))
        .annotate(day=TruncDate("forwarded_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["forwarded"] = r["c"]

    for r in (
        Application.objects.filter(organization=org, status="APPROVED", sapa_reviewed_at__range=(start_dt, end_dt))
        .annotate(day=TruncDate("sapa_reviewed_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["approved"] = r["c"]

    for r in (
        Application.objects.filter(organization=org, status="REJECTED", sapa_reviewed_at__range=(start_dt, end_dt))
        .annotate(day=TruncDate("sapa_reviewed_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["rejected"] = r["c"]

    # Enrollments
    for r in (
        Enrollment.objects.filter(organization=org, created_at__range=(start_dt, end_dt))
        .annotate(day=TruncDate("created_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["enrollments_created"] = r["c"]

    # Logistics
    for r in (
        MonthlySupply.objects.filter(
            enrollment__organization=org,
            delivered_on__gte=start_day,
            delivered_on__lte=end_day,
        )
        .values("delivered_on")
        .annotate(c=Count("id"))
    ):
        by_day[r["delivered_on"]]["supplies_delivered"] = r["c"]

    # Compliance
    for r in (
        ComplianceSubmission.objects.filter(
            monthly_supply__enrollment__organization=org,
            submitted_at__range=(start_dt, end_dt),
        )
        .annotate(day=TruncDate("submitted_at", tzinfo=tz))
        .values("day")
        .annotate(
            submitted=Count("id"),
            compliant=Count("id", filter=Q(status="COMPLIANT")),
            unable=Count("id", filter=Q(status="UNABLE")),
        )
    ):
        by_day[r["day"]]["compliance_submitted"] = r["submitted"]
        by_day[r["day"]]["compliance_compliant"] = r["compliant"]
        by_day[r["day"]]["compliance_unable"] = r["unable"]

    # Milestones
    for r in (
        ScreeningMilestone.objects.filter(enrollment__organization=org, due_on__gte=start_day, due_on__lte=end_day)
        .values("due_on")
        .annotate(c=Count("id"))
    ):
        by_day[r["due_on"]]["milestones_due"] = r["c"]

    for r in (
        ScreeningMilestone.objects.filter(
            enrollment__organization=org,
            status="OVERDUE",
            updated_at__range=(start_dt, end_dt),
        )
        .annotate(day=TruncDate("updated_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["milestones_overdue"] = r["c"]

    for r in (
        ScreeningMilestone.objects.filter(
            enrollment__organization=org,
            status="COMPLETED",
            completed_at__range=(start_dt, end_dt),
        )
        .annotate(day=TruncDate("completed_at", tzinfo=tz))
        .values("day")
        .annotate(c=Count("id"))
    ):
        by_day[r["day"]]["milestones_completed"] = r["c"]

    now = timezone.now()
    rows = [
        SchoolStatDaily(
            organization=org,
            day=day,
            created_at=now,
            updated_at=now,
            **by_day[day],
        )
        for day in days
    ]

    SchoolStatDaily.objects.filter(organization=org, day__gte=start_day, day__lte=end_day).delete()
    SchoolStatDaily.objects.bulk_create(rows, batch_size=500)

    rs, _ = SchoolReportStatus.objects.get_or_create(organization=org)
    rs.ensure_defaults()

    return len(rows)

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

def ensure_rollups_for_period(
    org: Organization,
    start_day: date,
    end_day: date,
    *,
    rebuild_recent_days: int = 2,
) -> int:
    """Ensure SchoolStatDaily rows exist and are current for a given period."""
    if start_day > end_day:
        return 0

    existing_days = set(
        SchoolStatDaily.objects.filter(
            organization=org,
            day__gte=start_day,
            day__lte=end_day,
        ).values_list("day", flat=True)
    )

    recent = set()
    for i in range(max(0, rebuild_recent_days)):
        recent.add(end_day - timedelta(days=i))

    days_to_build: list[date] = []
    d = start_day
    while d <= end_day:
        if (d not in existing_days) or (d in recent):
            days_to_build.append(d)
        d += timedelta(days=1)

    total_days = (end_day - start_day).days + 1
    if total_days >= 14 and len(days_to_build) >= int(total_days * 0.6):
        build_rollups_for_period_bulk(org, start_day, end_day)
        return total_days

    for day in days_to_build:
        build_daily_rollup(org, day)

    return len(days_to_build)


def ensure_rollups_caught_up(
    org: Organization,
    start_day: date,
    end_day: date,
    *,
    rebuild_recent_days: int = 2,
) -> int:
    """Catch up missing rollups and refresh recent days."""
    if start_day > end_day:
        return 0

    last_day = (
        SchoolStatDaily.objects.filter(organization=org)
        .order_by("-day")
        .values_list("day", flat=True)
        .first()
    )

    if not last_day or last_day < start_day:
        if not last_day:
            has_activity = (
                Screening.objects.filter(organization=org, screened_at__date__range=(start_day, end_day)).exists()
                or Application.objects.filter(organization=org, applied_at__date__range=(start_day, end_day)).exists()
            )
            if not has_activity:
                return 0

        return ensure_rollups_for_period(
            org,
            start_day,
            end_day,
            rebuild_recent_days=rebuild_recent_days,
        )

    if last_day < end_day:
        backfill_start = max(start_day, last_day + timedelta(days=1))
        return ensure_rollups_for_period(
            org,
            backfill_start,
            end_day,
            rebuild_recent_days=rebuild_recent_days,
        )

    refresh_start = max(start_day, end_day - timedelta(days=max(0, rebuild_recent_days - 1)))
    return ensure_rollups_for_period(
        org,
        refresh_start,
        end_day,
        rebuild_recent_days=rebuild_recent_days,
    )
