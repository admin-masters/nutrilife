from __future__ import annotations
import csv, io, os
from datetime import timedelta
from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone
from accounts.models import Organization
from .models import SchoolReportStatus
from .services import build_rollups_for_day, period_summary, six_month_window_ending

@shared_task
def build_daily_rollups():
    # roll up "yesterday" so the day is complete
    day = (timezone.now() - timedelta(days=1)).date()
    build_rollups_for_day(day)

def _make_school_performance_csv(org: Organization, start_day, end_day) -> bytes:
    agg = period_summary(org, start_day, end_day)
    buff = io.StringIO()
    w = csv.writer(buff)
    # Header
    w.writerow(["School", org.name])
    w.writerow(["Period", f"{start_day} to {end_day}"])
    w.writerow([])
    # Summary KPIs
    w.writerow(["Metric","Value"])
    for k in ["screened","red_flags","applied","forwarded","approved","rejected",
              "enrollments_created","supplies_delivered",
              "compliance_submitted","compliance_compliant","compliance_unable",
              "milestones_due","milestones_overdue","milestones_completed",
              "red_rate","compliance_rate"]:
        w.writerow([k, agg.get(k, 0)])
    return buff.getvalue().encode("utf-8")

@shared_task
def send_due_school_reports():

    today = timezone.now().date()
    to_recipients = [e.strip() for e in (os.getenv("ESAPA_REPORT_TO","").split(",")) if e.strip()]
    if not to_recipients:
        return 0

    sent = 0
    for org in Organization.objects.all().iterator():
        rs, _ = SchoolReportStatus.objects.get_or_create(organization=org)
        rs.ensure_defaults()
        if rs.next_due_on and rs.next_due_on <= today:
            start, end = six_month_window_ending(today)
            csv_bytes = _make_school_performance_csv(org, start, end)
            filename = f"{org.name.replace(' ','_')}_performance_{start}_{end}.csv"
            email = EmailMessage(
                subject=f"Nutrilift – {org.name} six‑month performance report",
                body=(f"Attached is the performance report for {org.name} covering {start} to {end}.\n"
                      f"This export was generated automatically by the system."),
                to=to_recipients,
            )
            email.attach(filename, csv_bytes, "text/csv")
            email.send(fail_silently=True)

            rs.last_sent_at = timezone.now()
            rs.last_period_start = start
            rs.last_period_end = end
            rs.next_due_on = today + timedelta(days=180)
            rs.save(update_fields=["last_sent_at","last_period_start","last_period_end","next_due_on","updated_at"])
            sent += 1
    return sent
