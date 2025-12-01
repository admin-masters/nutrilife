from datetime import timedelta
from django.db.models import Q, OuterRef, Subquery
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from accounts.decorators import require_roles
from accounts.models import Role
from roster.models import Student, Classroom, Guardian
from .forms import ScreeningForm, MCQ_FIELDS
from .models import Screening
from .services import compute_risk
from audit.utils import audit_log
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from accounts.decorators import require_roles
from accounts.models import Role
from messaging.services import send_redflag_education, send_redflag_assistance
from roster.models import Guardian
from .models import Screening 

# near top with other imports
from django.db import transaction, IntegrityError
from django.shortcuts import render
from .forms import AddStudentForm  # add AddStudentForm


def _org_required(request):
    return getattr(request, "org", None) is not None

@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
def teacher_portal(request):
    if not _org_required(request):
        return HttpResponseForbidden("Organization context required.")
    org = request.org

    classroom_id = request.GET.get("classroom")
    risk = request.GET.get("risk")  # GREEN|AMBER|RED
    q = request.GET.get("q", "").strip()

    # Annotate each student with last risk level (Subquery)
    last_screening = Screening.objects.filter(student=OuterRef("pk")).order_by("-screened_at").values("risk_level")[:1]
    students = Student.objects.filter(organization=org).annotate(last_risk=Subquery(last_screening))
    if classroom_id:
        students = students.filter(classroom_id=classroom_id)
    if risk in {"GREEN","AMBER","RED"}:
        students = students.filter(last_risk=risk)
    if q:
        students = students.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))
    students = students.order_by("last_name", "first_name")  # alphabetical (p.14)

    classrooms = Classroom.objects.filter(organization=org).order_by("grade","division")
    return render(request, "screening/teacher_portal.html", {
        "students": students,
        "classrooms": classrooms,
        "selected_classroom": int(classroom_id) if classroom_id else None,
        "selected_risk": risk or "",
        "q": q,
    })

@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
def screening_create(request, student_id):
    if not _org_required(request):
        return HttpResponseForbidden("Organization context required.")
    org = request.org
    student = get_object_or_404(Student, pk=student_id, organization=org)

    if request.method == "POST":
        form = ScreeningForm(request.POST, student=student)
        if form.is_valid():
            s = Screening(
                organization=org,
                student=student,
                teacher=request.user,
                screened_at=timezone.now(),
                height_cm=form.cleaned_data["height_cm"],
                weight_kg=form.cleaned_data["weight_kg"],
                age_years=form.cleaned_data["age_years"],
                gender=form.cleaned_data["gender"],
                answers=form.cleaned_data["answers"],
                is_low_income_at_screen=form.cleaned_data["is_low_income_at_screen"],
            )
            # --- risk compute (unchanged) ---
            rr = compute_risk(
                age_years=s.age_years,
                gender=s.gender,
                height_cm=float(s.height_cm) if s.height_cm else None,
                weight_kg=float(s.weight_kg) if s.weight_kg else None,
                answers=s.answers or {},
            )
            s.risk_level = rr.level
            s.red_flags = rr.red_flags
            s.save()

            # --- guardian link (unchanged) ---
            phone = form.cleaned_data.get("parent_phone_e164", "").strip()
            if phone:
                guardian, _ = Guardian.objects.get_or_create(
                    organization=org, phone_e164=phone,
                    defaults={"full_name": "Parent", "whatsapp_opt_in": True}
                )
                if not student.primary_guardian_id:
                    student.primary_guardian = guardian
                    student.save(update_fields=["primary_guardian"])

            audit_log(request.user, org, "SCREENING_CREATED", target=s, payload={"risk": s.risk_level})

            return redirect(reverse("screening_result", args=[s.id]))
        else:
            # ------- re-render with field errors -------
            mcq_fields = [form[field_key] for field_key, _ in MCQ_FIELDS]
            return render(
                request,
                "screening/screening_form.html",
                {"student": student, "form": form, "mcq_fields": mcq_fields},
            )
    else:
        form = ScreeningForm(student=student, initial={"is_low_income_at_screen": student.is_low_income})
        mcq_fields = [form[field_key] for field_key, _ in MCQ_FIELDS]
        return render(
            request,
            "screening/screening_form.html",
            {"student": student, "form": form, "mcq_fields": mcq_fields},
        )
    return render(request, "screening/screening_form.html", {"student": student, "form": form, "MCQ_FIELDS": MCQ_FIELDS})

@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
def screening_result(request, screening_id):
    if not _org_required(request):
        return HttpResponseForbidden("Organization context required.")
    org = request.org
    s = get_object_or_404(Screening, pk=screening_id, organization=org)

    # WhatsApp pre-filled message links (opened on teacher device). Real template sending in Sprint 2.
    parent_phone = s.student.primary_guardian.phone_e164 if s.student.primary_guardian else ""
    report = f"Screening result for {s.student.full_name}: {s.risk_level}. Flags: {', '.join(s.red_flags) or 'none'}."
    education_msg = (report + " Please watch this short video on nutrition and consult your pediatrician."
                     " Video: https://example.org/nutrition-video")
    assistance_msg = (report + " Your child may be eligible for supplementation support. "
                      "Learn more and apply here: https://example.org/support-apply")

    def wa_link(text):
        if not parent_phone:
            return ""
        from urllib.parse import quote_plus
        return f"https://wa.me/{parent_phone.replace('+','')}/?text={quote_plus(text)}"

    links = {
        "education_link": wa_link(education_msg),
        "assistance_link": wa_link(assistance_msg) if s.is_low_income_at_screen else "",
    }

    return render(request, "screening/screening_result.html", {"s": s, "links": links})


@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
def send_education(request, screening_id):
    s = get_object_or_404(Screening, pk=screening_id, organization=request.org)
    # basic guards
    if not s.student.primary_guardian or not s.student.primary_guardian.phone_e164:
        messages.error(request, "Parent WhatsApp number missing.")
        return redirect("screening_result", screening_id=s.id)
    log = send_redflag_education(s)
    messages.success(request, f"Education message queued → status {log.status}.")
    return redirect("screening_result", screening_id=s.id)

@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
def send_assistance(request, screening_id):
    s = get_object_or_404(Screening, pk=screening_id, organization=request.org)
    if not s.is_low_income_at_screen and not s.student.is_low_income:
        messages.error(request, "Assistance flow is for low-income students only.")
        return redirect("screening_result", screening_id=s.id)
    if not s.student.primary_guardian or not s.student.primary_guardian.phone_e164:
        messages.error(request, "Parent WhatsApp number missing.")
        return redirect("screening_result", screening_id=s.id)
    log = send_redflag_assistance(s)
    messages.success(request, f"Assistance message queued → status {log.status}.")
    return redirect("screening_result", screening_id=s.id)

# Add somewhere near other helpers in this file
def _generate_student_code(org) -> str:
    """
    Generate a short numeric code unique within the organization.
    Keep it simple; retry a few times on collision.
    """
    import random
    for _ in range(15):
        code = "".join(random.choices("0123456789", k=6))
        if not Student.objects.filter(organization=org, student_code=code).exists():
            return code
    # Fallback – extremely unlikely to be needed
    raise ValueError("Could not generate a unique student code. Please enter one manually.")

@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
def teacher_add_student(request):
    # Ensure org context is present
    if not getattr(request, "org", None):
        return HttpResponseForbidden("Organization context required.")
    org = request.org

    # Prefill grade/division if teacher clicked from a classroom filter
    initial = {}
    classroom_id = request.GET.get("classroom")
    if classroom_id:
        c = Classroom.objects.filter(id=classroom_id, organization=org).first()
        if c:
            initial["grade"] = c.grade
            initial["division"] = c.division

    if request.method == "POST":
        form = AddStudentForm(request.POST, organization=org)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Guardian: reuse if phone exists in this org, else create
                    g_phone = form.cleaned_data["guardian_phone_e164"]
                    guardian, created_guardian = Guardian.objects.get_or_create(
                        organization=org, phone_e164=g_phone,
                        defaults={
                            "full_name": form.cleaned_data["guardian_full_name"],
                            "whatsapp_opt_in": form.cleaned_data.get("whatsapp_opt_in", True),
                            "preferred_language": form.cleaned_data.get("preferred_language") or "en",
                        }
                    )
                    # Optionally refresh guardian fields (without clobbering intentionally set values)
                    updates = []
                    if not guardian.full_name and form.cleaned_data["guardian_full_name"]:
                        guardian.full_name = form.cleaned_data["guardian_full_name"]; updates.append("full_name")
                    pref_lang = form.cleaned_data.get("preferred_language") or "en"
                    if guardian.preferred_language != pref_lang:
                        guardian.preferred_language = pref_lang; updates.append("preferred_language")
                    if form.cleaned_data.get("whatsapp_opt_in") and not guardian.whatsapp_opt_in:
                        guardian.whatsapp_opt_in = True; updates.append("whatsapp_opt_in")
                    if updates:
                        guardian.save(update_fields=updates)

                    # Classroom: reuse existing or create new (unique_together handles duplicates)
                    classroom, _ = Classroom.objects.get_or_create(
                        organization=org,
                        grade=form.cleaned_data["grade"].strip(),
                        division=(form.cleaned_data.get("division") or "").strip(),
                    )

                    # Student code: generate if blank
                    code = (form.cleaned_data.get("student_code") or "").strip() or _generate_student_code(org)

                    # Create the student
                    student = Student.objects.create(
                        organization=org,
                        classroom=classroom,
                        first_name=form.cleaned_data["first_name"].strip(),
                        last_name=(form.cleaned_data.get("last_name") or "").strip(),
                        gender=form.cleaned_data["gender"],
                        dob=form.cleaned_data.get("dob"),
                        is_low_income=form.cleaned_data.get("is_low_income", False),
                        student_code=code,
                        primary_guardian=guardian,
                    )

                messages.success(request, f"Student “{student.full_name}” created.")
                audit_log(
                    request.user, org,
                    action="teacher_add_student",
                    target=student,
                    payload={"guardian_id": guardian.id},
                    request=request
                )
                # Go straight to screening for this new student
                return redirect("screening_create", student_id=student.id)

            except (IntegrityError, ValueError) as e:
                messages.error(request, f"Could not create student: {e}")

    else:
        form = AddStudentForm(organization=org, initial=initial)

    return render(request, "screening/add_student.html", {"form": form})
