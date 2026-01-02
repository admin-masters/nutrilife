from __future__ import annotations
import csv, io
from datetime import timedelta, date
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from accounts.decorators import require_roles
from accounts.models import Role, Organization
from .models import SchoolStatDaily, SchoolReportStatus
from .services import period_summary, six_month_window_ending
from django.contrib.auth.decorators import login_required
from .services import period_summary, ensure_rollups_caught_up
from assist.models import Application

def _six_months():
    end = timezone.now().date()
    start = end - timedelta(days=180)
    return start, end

@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def school_dashboard(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    start, end = _six_months()
    agg = period_summary(org, start, end)
    # trend: last 30 days screened
    last30 = end - timedelta(days=29)
    trend = (SchoolStatDaily.objects
             .filter(organization=org, day__gte=last30, day__lte=end)
             .order_by("day"))

    rs, _ = SchoolReportStatus.objects.get_or_create(organization=org)
    ctx = {"org": org, "start": start, "end": end, "agg": agg, "trend": trend, "report_status": rs}
    return render(request, "reporting/school_dashboard.html", ctx)

@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def export_school_csv(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    # allow custom range; default 6 months
    def _parse(d):
        try: return date.fromisoformat(d)
        except Exception: return None
    start = _parse(request.GET.get("start")) or (timezone.now().date() - timedelta(days=180))
    end = _parse(request.GET.get("end")) or timezone.now().date()

    agg = period_summary(org, start, end)
    buff = io.StringIO()
    w = csv.writer(buff)
    w.writerow(["School", org.name])
    w.writerow(["Period", f"{start} to {end}"])
    w.writerow([])
    w.writerow(["Metric","Value"])
    for k,v in agg.items():
        w.writerow([k, v])
    resp = HttpResponse(buff.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{org.name.replace(" ","_")}_{start}_{end}_summary.csv"'
    return resp

@require_roles(Role.INDITECH, allow_superuser=True)
def inditech_dashboard(request):
    # summary across all schools for the last 6 months + next_due_on
    start, end = _six_months()
    rows = []
    for org in Organization.objects.filter(
        org_type__in=[Organization.OrgType.SCHOOL, Organization.OrgType.NGO]
    ).order_by("name"):
        agg = period_summary(org, start, end)
        rs, _ = SchoolReportStatus.objects.get_or_create(organization=org)
        rows.append({
            "org": org,
            "agg": agg,
            "next_due_on": rs.next_due_on,
            "last_sent_at": rs.last_sent_at,
        })
    return render(request, "reporting/inditech_dashboard.html", {"rows": rows, "start": start, "end": end})

@require_roles(Role.INDITECH, allow_superuser=True)
def inditech_school(request, org_id: int):
    org = get_object_or_404(
        Organization,
        pk=org_id,
        org_type__in=[Organization.OrgType.SCHOOL, Organization.OrgType.NGO],
    )

    start, end = _six_months()
    agg = period_summary(org, start, end)
    rs, _ = SchoolReportStatus.objects.get_or_create(organization=org)
    # trend
    last30 = end - timedelta(days=29)
    trend = (SchoolStatDaily.objects
             .filter(organization=org, day__gte=last30, day__lte=end)
             .order_by("day"))
    return render(request, "reporting/inditech_school.html", {"org": org, "agg": agg, "trend": trend, "start": start, "end": end, "report_status": rs})

@require_roles(Role.INDITECH, allow_superuser=True)
def inditech_export_school_csv(request, org_id: int):
    org = get_object_or_404(
        Organization,
        pk=org_id,
        org_type__in=[Organization.OrgType.SCHOOL, Organization.OrgType.NGO],
    )

    start, end = _six_months()
    agg = period_summary(org, start, end)
    buff = io.StringIO()
    w = csv.writer(buff)
    w.writerow(["School", org.name])
    w.writerow(["Period", f"{start} to {end}"])
    w.writerow([])
    w.writerow(["Metric","Value"])
    for k,v in agg.items():
        w.writerow([k, v])
    resp = HttpResponse(buff.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{org.name.replace(" ","_")}_{start}_{end}_summary.csv"'
    return resp

@login_required
def inditech_console(request):
    # Teachers are regular users; only staff should see this console.
    if not request.user.is_staff:
        return HttpResponseForbidden("Forbidden")
    return HttpResponse("Inditech Console")  # simple 200 for staff

@require_roles(Role.INDITECH, allow_superuser=True)
def inditech_school_applications(request, org_id: int, bucket: str):
    """List supplement requests (assist.Application) for a school.

    Buckets:
      * pending  -> APPLIED + FORWARDED
      * approved -> APPROVED
      * rejected -> REJECTED
    """
    org = get_object_or_404(
        Organization,
        pk=org_id,
        org_type__in=[Organization.OrgType.SCHOOL, Organization.OrgType.NGO],
    )

    bucket = (bucket or "").strip().lower()
    if bucket == "pending":
        statuses = [Application.Status.APPLIED, Application.Status.FORWARDED]
        heading = "Pending applications"
    elif bucket == "approved":
        statuses = [Application.Status.APPROVED]
        heading = "Approved applications"
    elif bucket == "rejected":
        statuses = [Application.Status.REJECTED]
        heading = "Rejected applications"
    else:
        return HttpResponseForbidden("Invalid application bucket")

    apps = (
        Application.objects.filter(organization=org, status__in=statuses)
        .select_related("organization", "student", "guardian")
        .order_by("-applied_at")
    )

    return render(
        request,
        "reporting/inditech_school_applications.html",
        {
            "org": org,
            "bucket": bucket,
            "heading": heading,
            "applications": apps,
        },
    )
