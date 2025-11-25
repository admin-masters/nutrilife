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
import re

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
@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def school_app_dashboard(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")

    q_status = request.GET.get("status", "APPLIED")
    qs = Application.objects.filter(organization=org)
    counts = {
        "APPLIED": qs.filter(status=Application.Status.APPLIED).count(),
        "FORWARDED": qs.filter(status=Application.Status.FORWARDED).count(),
    }
    if q_status in ("APPLIED", "FORWARDED"):
        qs = qs.filter(status=q_status)

    applications = qs.select_related("student", "guardian").order_by("-applied_at")[:500]
    return render(request, "assist/school_admin_list.html", {
        "org": org,
        "applications": applications,
        "counts": counts,
        "status": q_status,
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
