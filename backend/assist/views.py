from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.db import transaction
from accounts.decorators import require_roles
from accounts.models import Role
from audit.utils import audit_log
from roster.models import Student, Guardian
from screening.models import Screening
from .models import Application
from .forms import ParentConsentForm
from datetime import datetime, date
import calendar


# ---------- Public parent application (consent) ----------
def assist_apply(request):
    """
    Landing page from WhatsApp link (Sprint 2).
    Expects: ?student_id=&screening_id=&lang=
    """
    try:
        student_id = int(request.GET.get("student_id", "0"))
        screening_id = int(request.GET.get("screening_id", "0"))
    except ValueError:
        return HttpResponseBadRequest("Invalid parameters.")

    raw_lang = (request.GET.get("lang") or "").lower()
    m = re.search(r'\b(en|hi|local)\b', raw_lang)   # keep only supported codes
    lang = m.group(1) if m else "en"
    screening = get_object_or_404(Screening, pk=screening_id)
    student = get_object_or_404(Student, pk=student_id, organization=screening.organization)

    # If an APPLIED/ FORWARDED exists recently, show an info banner (idempotency UX)
    existing = Application.objects.filter(organization=screening.organization, student=student)\
                                  .order_by("-applied_at").first()

    if request.method == "POST":
        form = ParentConsentForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Link or create guardian from parent phone (if provided)
                g = None
                phone = (form.cleaned_data.get("parent_phone_e164") or "").strip()
                if phone:
                    g, _ = Guardian.objects.get_or_create(
                        organization=screening.organization,
                        phone_e164=phone,
                        defaults={"full_name": form.cleaned_data.get("parent_full_name") or "Parent"}
                    )
                    # attach primary guardian if missing
                    if not student.primary_guardian_id:
                        student.primary_guardian = g
                        student.save(update_fields=["primary_guardian"])

                app = Application.objects.create(
                    organization=screening.organization,
                    student=student,
                    guardian=g,
                    source=Application.Source.PARENT,
                    status=Application.Status.APPLIED,
                    form_lang=lang,
                    form_data=form.as_form_data()
                )
                audit_log(user=None, org=screening.organization, action="APPLICATION_APPLIED", target=app,
                          payload={"screening_id": screening.id})

            return redirect(reverse("assist:assist_thanks") + f"?id={app.id}")
    else:
        form = ParentConsentForm()

    return render(request, "assist/apply_form.html", {
        "screening": screening,
        "student": student,
        "org": screening.organization,
        "form": form,
        "existing": existing,
        "lang": lang,
    })

def assist_thanks(request):
    return render(request, "assist/apply_success.html", {})


# ---------- School Admin dashboard + actions ----------
# backend/assist/views.py (helpers, above school_app_dashboard)
def _month_delta(d: date, months: int) -> date:
    """Return date shifted by `months` (can be negative), clamped to month end."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))

def _period_bounds(key: str):
    """
    key in {'3m','6m','12m','18m','all'} → (start_dt_or_None, end_dt)
    If 'all', returns (None, now).
    """
    key = (key or "3m").lower()
    now = timezone.now()
    if key == "all":
        return None, now
    months = {"3m": -3, "6m": -6, "12m": -12, "18m": -18}.get(key, -3)
    start_day = _month_delta(now.date(), months)
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start_day, datetime.min.time()), tz)
    return start_dt, now

# backend/assist/views.py (replace the function body of school_app_dashboard)
@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def school_app_dashboard(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")

    # Existing table filter by status (unchanged)
    q_status = request.GET.get("status", "APPLIED")
    app_qs = Application.objects.filter(organization=org)
    counts = {
        "APPLIED": app_qs.filter(status=Application.Status.APPLIED).count(),
        "FORWARDED": app_qs.filter(status=Application.Status.FORWARDED).count(),
    }
    if q_status in ("APPLIED", "FORWARDED"):
        app_qs = app_qs.filter(status=q_status)
    applications = app_qs.select_related("student", "guardian").order_by("-applied_at")[:500]

    # NEW: period filter for the summary metrics
    period = request.GET.get("period", "3m")
    start_dt, end_dt = _period_bounds(period)

    # Base screening queryset (optionally windowed)
    screenings = Screening.objects.filter(organization=org)
    if start_dt:
        screenings = screenings.filter(screened_at__range=(start_dt, end_dt))

    # Distinct-student screening counts
    screened_distinct = screenings.values_list("student_id", flat=True).distinct()
    total_screened = screened_distinct.count()
    total_redflag = (
        screenings.filter(risk_level=Screening.RiskLevel.RED)
        .values_list("student_id", flat=True)
        .distinct()
        .count()
    )
    boys_screened = (
        screenings.filter(student__gender="M")
        .values_list("student_id", flat=True)
        .distinct()
        .count()
    )
    boys_redflag = (
        screenings.filter(student__gender="M", risk_level=Screening.RiskLevel.RED)
        .values_list("student_id", flat=True)
        .distinct()
        .count()
    )
    girls_screened = (
        screenings.filter(student__gender="F")
        .values_list("student_id", flat=True)
        .distinct()
        .count()
    )
    girls_redflag = (
        screenings.filter(student__gender="F", risk_level=Screening.RiskLevel.RED)
        .values_list("student_id", flat=True)
        .distinct()
        .count()
    )

    # Applications metrics in the window
    apps = Application.objects.filter(organization=org)
    if start_dt:
        applications_pending = apps.filter(
            status=Application.Status.FORWARDED,
            forwarded_at__range=(start_dt, end_dt),
        ).count()
        applications_approved = apps.filter(
            status=Application.Status.APPROVED,
            forwarded_at__range=(start_dt, end_dt),  # cohort based on when they were sent
        ).count()
    else:
        # 'All' means unbounded
        applications_pending = apps.filter(status=Application.Status.FORWARDED).count()
        applications_approved = apps.filter(status=Application.Status.APPROVED).count()

    summary = {
        "total_students": Student.objects.filter(organization=org).count(),  # not windowed
        "total_screened": total_screened,
        "total_redflag": total_redflag,
        "applications_pending": applications_pending,
        "applications_approved": applications_approved,
        "boys_screened": boys_screened,
        "boys_redflag": boys_redflag,
        "girls_screened": girls_screened,
        "girls_redflag": girls_redflag,
    }

    return render(request, "assist/school_admin_list.html", {
        "org": org,
        "applications": applications,
        "counts": counts,   # keep existing keys to avoid breaking template conditionals
        "status": q_status,
        "period": period,
        "summary": summary,
    })


@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def forward_all(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")

    pending = Application.objects.filter(organization=org, status=Application.Status.APPLIED)
    updated = 0
    for app in pending.iterator():
        app.status = Application.Status.FORWARDED
        app.forwarded_at = timezone.now()
        app.forwarded_by = request.user
        app.save(update_fields=["status","forwarded_at","forwarded_by","updated_at"])
        audit_log(request.user, org, "APPLICATION_FORWARDED", target=app)
        updated += 1

    # Simple redirect back with a count param
    return redirect(reverse("assist:school_app_dashboard") + f"?status=APPLIED&forwarded={updated}")

@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def forward_one(request, app_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    app = get_object_or_404(Application, pk=app_id, organization=org, status=Application.Status.APPLIED)
    app.status = Application.Status.FORWARDED
    app.forwarded_at = timezone.now()
    app.forwarded_by = request.user
    app.save(update_fields=["status","forwarded_at","forwarded_by","updated_at"])
    audit_log(request.user, org, "APPLICATION_FORWARDED", target=app)
    return redirect(reverse("assist:school_app_dashboard") + "?status=APPLIED")
