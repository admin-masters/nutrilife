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
import json  
from django.core.exceptions import ValidationError
from messaging.ratelimit import RateLimitExceeded
from messaging.models import MessageLog
from django.contrib.auth.decorators import login_required
from accounts.models import Organization, OrgMembership, Role

from django.shortcuts import get_object_or_404, redirect
from accounts.models import Organization, OrgMembership
from .decorators import require_teacher_or_public
from messaging.services import (
    send_redflag_education, send_redflag_assistance,  # keep for other flows
    prepare_redflag_education_click_to_chat,
    prepare_redflag_assistance_click_to_chat,
)
def teacher_portal_token(request, token: str):
    """
    PUBLIC entry point. Resolves org by token, starts a 'public teacher' session for that org,
    and then shows the regular teacher portal (now guarded by require_teacher_or_public).
    """
    org = get_object_or_404(Organization, screening_link_token=token)

    # Start public teacher session for this org
    request.session["public_teacher_org_id"] = org.id

    # For immediate rendering convenience
    request.org = org

    # If the visitor happens to be logged in and a member, keep membership around for downstream use
    if request.user.is_authenticated:
        request.membership = OrgMembership.objects.filter(
            user=request.user, organization=org, is_active=True
        ).first()

    # Render the teacher portal using the same function used by authenticated teachers
    return teacher_portal(request)


def _org_required(request):
    return getattr(request, "org", None) is not None

def _auto_send_for_screening(request, s: Screening):
    """
    Decide and PREPARE (do NOT auto-send) the correct WhatsApp message
    after a screening is created. Returns the MessageLog to open Click-to-Chat.
    """
    guardian = getattr(s.student, "primary_guardian", None)
    phone = getattr(guardian, "phone_e164", "") if guardian else ""
    if not phone:
        messages.warning(request, "No parent WhatsApp on file — message not sent.")
        return None

    # Consider either the snapshot on the screening OR the student flag
    #low_income = bool(s.is_low_income_at_screen) or bool(getattr(s.student, "is_low_income", False))
    low_income = bool(s.is_low_income_at_screen)
    try:
        if s.risk_level == Screening.RiskLevel.RED and low_income:
            log, _text = prepare_redflag_assistance_click_to_chat(s)
            messages.success(request, "Assistance message prepared — open WhatsApp to send.")
            audit_log(request.user, request.org, "AUTO_PREP_ASSISTANCE",
                      target=s, payload={"message_id": log.id}, request=request)
        else:
            log, _text = prepare_redflag_education_click_to_chat(s)
            messages.success(request, "Education message prepared — open WhatsApp to send.")
            audit_log(request.user, request.org, "AUTO_PREP_EDUCATION",
                      target=s, payload={"message_id": log.id}, request=request)
        return log
    except RateLimitExceeded as e:
        messages.warning(request, f"Message not sent due to rate limits: {e}")
        return None
    except Exception as e:
        messages.error(request, f"Auto-send failed: {e}")
        return None

#@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
@require_teacher_or_public
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
        "teacher_token": request.org.screening_link_token,
    })

#@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
@require_teacher_or_public
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
                # Rebind if different, so messages go to the phone the teacher just entered
                if student.primary_guardian_id != guardian.id:
                    student.primary_guardian = guardian
                    student.save(update_fields=["primary_guardian"])
            
            log = _auto_send_for_screening(request, s)

            audit_log(request.user, org, "SCREENING_CREATED", target=s, payload={"risk": s.risk_level})
            if log:
                preview = reverse("whatsapp_preview", args=[log.id])
                preview += f"?next={reverse('screening_result', args=[s.id])}"
                return redirect(preview)
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

#@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
@require_teacher_or_public
def screening_result(request, screening_id):
    if not _org_required(request):
        return HttpResponseForbidden("Organization context required.")
    org = request.org
    s = get_object_or_404(Screening, pk=screening_id, organization=org)

    # Show the latest message (if any) associated to this screening
    last_message = MessageLog.objects.filter(related_screening=s).order_by("-created_at").first()

    return render(request, "screening/screening_result.html", {"s": s, "last_message": last_message})



#@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
@require_teacher_or_public
def send_education(request, screening_id):
    s = get_object_or_404(Screening, pk=screening_id, organization=request.org)
    # basic guards
    if not s.student.primary_guardian or not s.student.primary_guardian.phone_e164:
        messages.error(request, "Parent WhatsApp number missing.")
        return redirect("screening_result", screening_id=s.id)
    log, _text = prepare_redflag_education_click_to_chat(s)
    preview = reverse("whatsapp_preview", args=[log.id]) + f"?next={reverse('screening_result', args=[s.id])}"
    return redirect(preview)

#@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
@require_teacher_or_public
def send_assistance(request, screening_id):
    s = get_object_or_404(Screening, pk=screening_id, organization=request.org)
    if not s.is_low_income_at_screen and not s.student.is_low_income:
        messages.error(request, "Assistance flow is for low-income students only.")
        return redirect("screening_result", screening_id=s.id)
    if not s.student.primary_guardian or not s.student.primary_guardian.phone_e164:
        messages.error(request, "Parent WhatsApp number missing.")
        return redirect("screening_result", screening_id=s.id)
    log, _text = prepare_redflag_assistance_click_to_chat(s)
    preview = reverse("whatsapp_preview", args=[log.id]) + f"?next={reverse('screening_result', args=[s.id])}"
    return redirect(preview)

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

#@require_roles(Role.TEACHER, Role.ORG_ADMIN, allow_superuser=True)
@require_teacher_or_public
def teacher_add_student(request,token=None):
    # Ensure org context is present
    if not getattr(request, "org", None):
        return HttpResponseForbidden("Organization context required.")
    org = request.org

    # Pre-select from classroom filter, if present
    initial = {}
    selected_classroom_id = request.GET.get("classroom")
    if selected_classroom_id:
        c = Classroom.objects.filter(id=selected_classroom_id, organization=org).first()
        if c:
            initial["grade"] = c.grade
            initial["division"] = c.division

    # Build divisions-by-grade mapping for the template's client-side filtering
    divisions_by_grade = {}
    for g, d in Classroom.objects.filter(organization=org).values_list("grade", "division"):
        divisions_by_grade.setdefault(g, [])
        if d not in divisions_by_grade[g]:
            divisions_by_grade[g].append(d or "")

    if request.method == "POST":
        student_form = AddStudentForm(request.POST, organization=org, initial=initial)
        screening_form = ScreeningForm(request.POST, student=None)

        valid = student_form.is_valid() & screening_form.is_valid()
        # For new students we require parent phone to bind a guardian
        if valid and not screening_form.cleaned_data.get("parent_phone_e164"):
            screening_form.add_error("parent_phone_e164", "Parent WhatsApp number is required for a new student.")
            valid = False

        if valid:
            try:
                with transaction.atomic():
                    # Resolve classroom – do NOT create new classrooms here
                    grade = student_form.cleaned_data["grade"]
                    division = student_form.cleaned_data["division"] or ""
                    classroom = Classroom.objects.filter(organization=org, grade=grade, division=division).first()
                    if not classroom:
                        student_form.add_error(None, "Selected Grade/Division does not exist.")
                        raise ValidationError("Classroom missing")

                    # Guardian (by phone only), opt-in always True, default name 'Parent'
                    phone = screening_form.cleaned_data["parent_phone_e164"]
                    guardian, _ = Guardian.objects.get_or_create(
                        organization=org, phone_e164=phone,
                        defaults={"full_name": "Parent", "whatsapp_opt_in": True}
                    )
                    if not guardian.whatsapp_opt_in:
                        guardian.whatsapp_opt_in = True
                        guardian.save(update_fields=["whatsapp_opt_in"])

                    # Student code: always auto-generate
                    code = _generate_student_code(org)

                    # Create student (gender comes from screening snapshot)
                    student = Student.objects.create(
                        organization=org,
                        classroom=classroom,
                        first_name=student_form.cleaned_data["first_name"].strip(),
                        last_name="",
                        gender=screening_form.cleaned_data["gender"],
                        dob=student_form.cleaned_data.get("dob"),
                        is_low_income=student_form.cleaned_data.get("is_low_income", False),
                        student_code=code,
                        primary_guardian=guardian,
                    )

                    # Create screening (same logic as screening_create)
                    s = Screening(
                        organization=org,
                        student=student,
                        teacher=request.user,
                        screened_at=timezone.now(),
                        height_cm=screening_form.cleaned_data["height_cm"],
                        weight_kg=screening_form.cleaned_data["weight_kg"],
                        age_years=screening_form.cleaned_data["age_years"],
                        gender=screening_form.cleaned_data["gender"],
                        answers=screening_form.cleaned_data["answers"],
                        is_low_income_at_screen=student_form.cleaned_data.get("is_low_income", False),
                    )

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

                log = _auto_send_for_screening(request, s)

                messages.success(request, f"Student “{student.full_name}” created and screening completed.")
                audit_log(
                    request.user, org,
                    action="teacher_add_student_and_screen",
                    target=student,
                    payload={"guardian_id": guardian.id, "screening_id": s.id, "risk": s.risk_level},
                    request=request
                )
                if log:
                    preview = reverse("whatsapp_preview", args=[log.id]) + f"?next={reverse('screening_result', args=[s.id])}"
                    return redirect(preview)
                return redirect("screening_result", screening_id=s.id)

            except (IntegrityError, ValidationError, ValueError) as e:
                messages.error(request, f"Could not complete: {e}")

    else:
        student_form = AddStudentForm(organization=org, initial=initial)
        screening_form = ScreeningForm(student=None)

    # For rendering MCQs nicely like screening_form.html
    mcq_fields = [screening_form[field_key] for field_key, _ in MCQ_FIELDS]

    return render(
        request,
        "screening/add_student.html",
        {
            "form": student_form,  # legacy var (unused by the new template, but safe)
            "student_form": student_form,
            "screening_form": screening_form,
            "mcq_fields": mcq_fields,
            "divisions_by_grade": json.dumps(divisions_by_grade),
        },
    )
