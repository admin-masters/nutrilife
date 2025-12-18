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
import re
from .models import Application, BatchItem
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Subquery, DateTimeField
# --- NEW DETAIL VIEWS FOR METRICS ---

def _age_years(dob):
    if not dob:
        return None
    today = timezone.now().date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

def _students_metric_qs(org, metric: str, start_dt, end_dt):
    # Base queryset with useful relations for table rendering
    students = (
        Student.objects
        .filter(organization=org)
        .select_related("classroom", "primary_guardian")
    )

    # “In-window” screenings subqueries (to mirror the dashboard period filter)
    window_screenings = Screening.objects.filter(organization=org, student=OuterRef("pk"))
    window_red = window_screenings.filter(risk_level=Screening.RiskLevel.RED)
    if start_dt:  # when period != 'all'
        window_screenings = window_screenings.filter(screened_at__range=(start_dt, end_dt))
        window_red = window_red.filter(screened_at__range=(start_dt, end_dt))

    # For “Total students” (all-time indicators)
    ever_screened = Screening.objects.filter(organization=org, student=OuterRef("pk"))
    ever_red = ever_screened.filter(risk_level=Screening.RiskLevel.RED)

    students = students.annotate(
        screened_in_window=Exists(window_screenings),
        red_in_window=Exists(window_red),
        ever_screened=Exists(ever_screened),
        ever_red=Exists(ever_red),
    )

    m = (metric or "").lower()
    if m in ("screened", "total_screened"):
        students = students.filter(screened_in_window=True)
        title = "Total screened"
    elif m in ("redflag", "red_flagged", "total_redflagged"):
        students = students.filter(red_in_window=True)
        title = "Total red‑flagged"
    elif m in ("boys_screened", "boys-screened"):
        students = students.filter(gender="M", screened_in_window=True)
        title = "Total boys screened"
    elif m in ("boys_redflag", "boys-redflagged"):
        students = students.filter(gender="M", red_in_window=True)
        title = "Total boys red‑flagged"
    elif m in ("girls_screened", "girls-screened"):
        students = students.filter(gender="F", screened_in_window=True)
        title = "Total girls screened"
    elif m in ("girls_redflag", "girls-redflagged"):
        students = students.filter(gender="F", red_in_window=True)
        title = "Total girls red‑flagged"
    else:
        title = "Total students"  # ignores the period filter, like your tile

    students = students.order_by("classroom__grade", "classroom__division",
                                 "first_name", "last_name")
    return title, students

@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def metric_students(request, metric: str):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")

    period = request.GET.get("period", "3m")
    start_dt, end_dt = _period_bounds(period)

    title, qs = _students_metric_qs(org, metric, start_dt, end_dt)

    rows = []
    for s in qs.iterator():
        # For “Total students” show all-time indicators; otherwise, period-windowed
        screened_flag = bool(s.ever_screened) if title == "Total students" else bool(s.screened_in_window)
        red_flag = bool(s.ever_red) if title == "Total students" else bool(s.red_in_window)

        class_div = "-"
        if s.classroom:
            class_div = s.classroom.grade if s.classroom.division == "" else f"{s.classroom.grade} {s.classroom.division}"
        phone = getattr(getattr(s, "primary_guardian", None), "phone_e164", None)

        rows.append({
            "name": getattr(s, "full_name", f"{s.first_name} {s.last_name}".strip()),
            "class_div": class_div,
            "age": _age_years(getattr(s, "dob", None)),
            "phone": phone or "-",
            "screened": "Yes" if screened_flag else "No",
            "redflag": "Yes" if red_flag else "No",
        })

    paginator = Paginator(rows, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "assist/metric_students_list.html", {
        "org": org,
        "title": title,
        "period": period,
        "page_obj": page_obj,
        "total": paginator.count,
    })

@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def metric_applications(request, status: str):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")

    period = request.GET.get("period", "3m")
    start_dt, end_dt = _period_bounds(period)

    status_key = (status or "").lower()
    if status_key in ("pending", "forwarded"):
        title = "Applications pending"
        base = Application.objects.filter(organization=org, status=Application.Status.FORWARDED)
    elif status_key in ("approved",):
        title = "Applications approved"
        base = Application.objects.filter(organization=org, status=Application.Status.APPROVED)
    else:
        return HttpResponseBadRequest("Unknown applications metric.")

    # Keep the cohort consistent with the dashboard tiles (windowed by forwarded_at)
    if start_dt:
        base = base.filter(forwarded_at__range=(start_dt, end_dt))

    # Pull “approved_at” from BatchItem.created_at (one per approved app)
    approved_subq = (
        BatchItem.objects
        .filter(application=OuterRef("pk"), outcome=BatchItem.Outcome.APPROVED)
        .order_by("-created_at").values("created_at")[:1]
    )

    apps = (
        base.select_related("student__classroom", "student__primary_guardian")
            .annotate(approved_at=Subquery(approved_subq, output_field=DateTimeField()))
            .order_by("-applied_at")
    )

    rows = []
    for a in apps.iterator():
        s = a.student
        class_div = "-"
        if s.classroom:
            class_div = s.classroom.grade if s.classroom.division == "" else f"{s.classroom.grade} {s.classroom.division}"
        phone = getattr(getattr(s, "primary_guardian", None), "phone_e164", None)

        rows.append({
            "name": getattr(s, "full_name", f"{s.first_name} {s.last_name}".strip()),
            "class_div": class_div,
            "age": _age_years(getattr(s, "dob", None)),
            "phone": phone or "-",
            "applied_at": a.applied_at,
            "forwarded_at": a.forwarded_at,
            "status": "Approved" if a.status == Application.Status.APPROVED else "Pending",
            "approved_at": a.approved_at or "Pending",
        })

    paginator = Paginator(rows, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "assist/metric_applications_list.html", {
        "org": org,
        "title": title,
        "period": period,
        "page_obj": page_obj,
        "total": paginator.count,
    })

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
                    trigger_screening=screening,
                    low_income_declared=bool(getattr(screening, "is_low_income_at_screen", False)),
                    income_verification_status=Application.IncomeVerificationStatus.PENDING,
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
    teacher_link = request.build_absolute_uri(
        reverse("teacher_portal_token", args=[org.screening_link_token])
    )
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
        "teacher_link": teacher_link,
        "org": org,
        "applications": applications,
        "counts": counts,   # keep existing keys to avoid breaking template conditionals
        "status": q_status,
        "period": period,
        "summary": summary,
    })


@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def verify_income(request, app_id: int):
    """School admin marks a parent application as low-income verified.

    This is a precondition to forwarding the application to SAPA.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    app = get_object_or_404(Application, pk=app_id, organization=org, status=Application.Status.APPLIED)
    notes = (request.POST.get("notes") or "").strip()
    app.low_income_declared = True
    app.income_verification_status = Application.IncomeVerificationStatus.VERIFIED
    app.income_verified_at = timezone.now()
    app.income_verified_by = request.user
    if notes:
        app.income_verification_notes = notes
    app.save(update_fields=[
        "low_income_declared",
        "income_verification_status",
        "income_verified_at",
        "income_verified_by",
        "income_verification_notes",
        "updated_at",
    ])
    audit_log(request.user, org, "APPLICATION_INCOME_VERIFIED", target=app, payload={"notes": notes} if notes else None)
    return redirect(reverse("assist:school_app_dashboard") + "?status=APPLIED")


@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def reject_income(request, app_id: int):
    """School admin rejects the application as not eligible for low-income assistance."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    app = get_object_or_404(Application, pk=app_id, organization=org, status=Application.Status.APPLIED)
    notes = (request.POST.get("notes") or "").strip()
    app.income_verification_status = Application.IncomeVerificationStatus.REJECTED
    app.income_verified_at = timezone.now()
    app.income_verified_by = request.user
    if notes:
        app.income_verification_notes = notes
    # Treat as rejected at the school level (keeps it out of SAPA queue)
    app.status = Application.Status.REJECTED
    app.save(update_fields=[
        "status",
        "income_verification_status",
        "income_verified_at",
        "income_verified_by",
        "income_verification_notes",
        "updated_at",
    ])
    audit_log(request.user, org, "APPLICATION_INCOME_REJECTED", target=app, payload={"notes": notes} if notes else None)
    return redirect(reverse("assist:school_app_dashboard") + "?status=APPLIED")


@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def forward_all(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")

    # Only forward applications that are declared low-income and verified by the school.
    pending = Application.objects.filter(
        organization=org,
        status=Application.Status.APPLIED,
        low_income_declared=True,
        income_verification_status=Application.IncomeVerificationStatus.VERIFIED,
    )
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
    app = get_object_or_404(
        Application,
        pk=app_id,
        organization=org,
        status=Application.Status.APPLIED,
        low_income_declared=True,
        income_verification_status=Application.IncomeVerificationStatus.VERIFIED,
    )
    app.status = Application.Status.FORWARDED
    app.forwarded_at = timezone.now()
    app.forwarded_by = request.user
    app.save(update_fields=["status","forwarded_at","forwarded_by","updated_at"])
    audit_log(request.user, org, "APPLICATION_FORWARDED", target=app)
    return redirect(reverse("assist:school_app_dashboard") + "?status=APPLIED")

def school_applications(request):
    org = getattr(request, "org", None)  # how you currently get org
    if not org:
        # keep whatever you currently do when org is missing
        pass

    status = request.GET.get("status", "APPLIED")

    # This block copies the listing logic you currently use on /assist/admin:
    app_qs = Application.objects.filter(organization=org)
    counts = {
        "APPLIED": app_qs.filter(status=Application.Status.APPLIED).count(),
        "FORWARDED": app_qs.filter(status=Application.Status.FORWARDED).count(),
    }
    if status in ("APPLIED", "FORWARDED"):
        app_qs = app_qs.filter(status=status)

    applications = (
        app_qs.select_related("student", "guardian")
             .order_by("-applied_at")[:500]
    )

    return render(
        request,
        "assist/applications_list.html",
        {
            "org": org,
            "applications": applications,
            "counts": counts,
            "status": status,
        },
    )