import json
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, OuterRef, Subquery, Exists
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organization, OrgMembership
from audit.utils import audit_log
from messaging.models import MessageLog
from messaging.ratelimit import RateLimitExceeded
from messaging.services import prepare_screening_status_click_to_chat
from roster.models import Classroom, Guardian, Student

from .decorators import require_teacher_or_public
from .forms import AddStudentForm, NewScreeningForm
from .models import Screening
from .services import compute_risk
from assist.models import Application
import logging
logger = logging.getLogger(__name__)

def teacher_portal_token(request, token: str):
    try:
            org.screening_only_profile
            return redirect(reverse("screening_only:teacher_access_portal", args=[org.screening_link_token]))
    except Exception:
            pass

    org = get_object_or_404(Organization, screening_link_token=token)
    request.session["public_teacher_org_id"] = org.id
    request.org = org
    if request.user.is_authenticated:
        request.membership = OrgMembership.objects.filter(
            user=request.user, organization=org, is_active=True
        ).first()
    return teacher_portal(request)

def _teacher_fk(request):
    return request.user if getattr(request.user, "is_authenticated", False) else None

def _auto_send_for_screening(request, s):
    from django.contrib import messages

    # Preferred source: Student.primary_guardian (this is what your forms populate)
    guardian = getattr(s.student, "primary_guardian", None)

    # Fallback: if you ever use StudentGuardian links, try that too
    if guardian is None:
        link = s.student.guardian_links.select_related("guardian").first()
        guardian = link.guardian if link else None

    if not guardian or not getattr(guardian, "phone_e164", None):
        messages.warning(request, "No parent phone number is available; cannot prepare WhatsApp message.")
        return None

    try:
        # Screening-only orgs: multi-language parent WhatsApp message
        try:
            s.organization.screening_only_profile
            is_screening_only = True
        except Exception:
            is_screening_only = False

        if is_screening_only:
            from screening_only.services import prepare_screening_only_redflag_click_to_chat
            log, _text = prepare_screening_only_redflag_click_to_chat(request, s)
        else:
            log, _text = prepare_screening_status_click_to_chat(s)

        if log:
            messages.success(request, "WhatsApp message prepared. Please send to the parent.")
        return log

    except Exception:
        logger.exception("Auto-send whatsapp failed")
        messages.error(request, "Could not prepare WhatsApp message.")
        return None



@require_teacher_or_public
def teacher_portal(request):
    org = getattr(request, "org", None)
    if not org:
        return HttpResponseForbidden("Organization context required.")

    classroom_id = request.GET.get("classroom")
    risk = request.GET.get("risk")  # GREEN|YELLOW|RED
    q = (request.GET.get("q") or "").strip()

    last_screening = (
    Screening.objects
        .filter(student=OuterRef("pk"))
        .order_by("-screened_at")
        .values("risk_level")[:1]
    )
    approved_application = (
        Application.objects
        .filter(
            organization=org,
            student=OuterRef("pk"),
            status=Application.Status.APPROVED,
        )
    )
    students = (
        Student.objects
        .filter(organization=org)
        .annotate(
            last_risk=Subquery(last_screening),
            supplements_granted=Exists(approved_application),
        )
    )
    
    if classroom_id:
        students = students.filter(classroom_id=classroom_id)
    if risk in {"GREEN", "YELLOW", "RED"}:
        students = students.filter(last_risk=risk)
    if q:
        students = students.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(student_code__icontains=q))

    students = students.order_by("last_name", "first_name")
    classrooms = Classroom.objects.filter(organization=org).order_by("grade", "division")

    return render(request, "screening/teacher_portal.html", {
        "students": students,
        "classrooms": classrooms,
        "selected_classroom": int(classroom_id) if classroom_id else None,
        "selected_risk": risk or "",
        "q": q,
        "teacher_token": org.screening_link_token,
    })

def _warn_if_large_change(student: Student, height_cm: float, weight_kg: float, now_dt):
    prev = Screening.objects.filter(student=student, screened_at__gte=now_dt - timedelta(days=183)).order_by("-screened_at").first()
    if not prev:
        return []
    warnings = []
    try:
        if prev.weight_kg is not None and abs(float(prev.weight_kg) - float(weight_kg)) > 10:
            warnings.append("Weight changed by > 10kg in ~6 months. Please verify readings.")
        if prev.height_cm is not None and abs(float(prev.height_cm) - float(height_cm)) > 10:
            warnings.append("Height changed by > 10cm in ~6 months. Please verify readings.")
    except Exception:
        pass
    return warnings

@require_teacher_or_public
def screening_create(request, student_id: int):
    org = getattr(request, "org", None)
    if not org:
        return HttpResponseForbidden("Organization context required.")
    student = get_object_or_404(Student, pk=student_id, organization=org)

    if request.method == "POST":
        form = NewScreeningForm(request.POST, student=student)
        if form.is_valid():
            derived = form.cleaned_data["_derived"]
            answers = form.cleaned_data["answers"]

            # Update student master
            student.student_code = answers.get("unique_student_id") or student.student_code
            student.dob = form.cleaned_data.get("dob") or student.dob
            student.gender = form.cleaned_data.get("sex") or student.gender
            student.save(update_fields=["student_code", "dob", "gender", "updated_at"])

            # Guardian (mandatory)
            phone = form.cleaned_data["parent_phone_e164"]
            guardian, _ = Guardian.objects.get_or_create(
                organization=org, phone_e164=phone,
                defaults={"full_name": "Parent", "whatsapp_opt_in": True}
            )
            if student.primary_guardian_id != guardian.id:
                student.primary_guardian = guardian
                student.save(update_fields=["primary_guardian", "updated_at"])

            now_dt = timezone.now()
            height_cm = float(derived["height_cm"])
            weight_kg = float(derived["weight_kg"])

            for w in _warn_if_large_change(student, height_cm, weight_kg, now_dt):
                messages.warning(request, w)

            s = Screening(
                organization=org,
                student=student,
                teacher=_teacher_fk(request),
                screened_at=now_dt,
                gender=student.gender,
                age_years=derived["age_years"],
                age_months=derived["age_months"],
                height_cm=height_cm,
                weight_kg=weight_kg,
                muac_cm=derived.get("muac_cm"),
                answers=answers,
                is_low_income_at_screen=bool(getattr(student, "is_low_income", False)),
            )

            rr = compute_risk(
                age_years=float(derived["age_years"]),
                age_months=int(derived["age_months"]),
                sex=student.gender,
                height_cm=height_cm,
                weight_kg=weight_kg,
                muac_cm=float(derived["muac_cm"]) if derived.get("muac_cm") is not None else None,
                answers=answers,
            )
            s.risk_level = rr.level
            s.red_flags = rr.flags
            if rr.derived.get("bmi") is not None:
                s.bmi = rr.derived["bmi"]
            if rr.derived.get("baz") is not None:
                s.baz = rr.derived["baz"]
            s.save()

            log = _auto_send_for_screening(request, s)
            audit_log(_teacher_fk(request), org, "SCREENING_CREATED", target=s, payload={"risk": s.risk_level})
            dashboard_url = reverse("screening_only:teacher_dashboard")
            if log:
                preview = reverse("whatsapp_preview", args=[log.id]) + f"?next={dashboard_url}"
                
                return redirect(preview)
            return redirect(dashboard_url)

        return render(request, "screening/screening_form.html", {"student": student, "form": form})

    form = NewScreeningForm(student=student)
    return render(request, "screening/screening_form.html", {"student": student, "form": form})

@require_teacher_or_public
def screening_result(request, screening_id: int):
    org = getattr(request, "org", None)
    if not org:
        return HttpResponseForbidden("Organization context required.")
    s = get_object_or_404(Screening, pk=screening_id, organization=org)
    last_message = MessageLog.objects.filter(related_screening=s).order_by("-created_at").first()

    teacher_view = {
        "GREEN": "Child’s growth and diet look on track.",
        "YELLOW": "Some areas need attention (e.g., low veg/fruit or fewer protein servings).",
        "RED": "Child shows signs needing a check-up (e.g., growth outside healthy range / possible anemia).",
    }.get((s.risk_level or "").upper(), "")

    return render(request, "screening/screening_result.html", {
        "s": s,
        "last_message": last_message,
        "teacher_view": teacher_view,
    })

@require_teacher_or_public
def send_parent_whatsapp(request, screening_id):
    s = get_object_or_404(Screening, id=screening_id, organization=request.org)
    log = _auto_send_for_screening(request, s)
    dashboard_url = reverse("screening_only:teacher_dashboard")

    if log:
        preview = reverse("whatsapp_preview", args=[log.id]) + f"?next={dashboard_url}"
        return redirect(preview)
    return redirect(dashboard_url)


@require_teacher_or_public
def teacher_add_student(request, token=None):
    org = getattr(request, "org", None)
    if not org:
        return HttpResponseForbidden("Organization context required.")

    initial = {}
    selected_classroom_id = request.GET.get("classroom")
    if selected_classroom_id:
        c = Classroom.objects.filter(id=selected_classroom_id, organization=org).first()
        if c:
            initial["grade"] = c.grade
            initial["division"] = c.division

    preferred_division_order = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + ["Other"]
    division_rank = {d: i for i, d in enumerate(preferred_division_order)}
    divisions_by_grade = {}
    for g, d in Classroom.objects.filter(organization=org).values_list("grade", "division"):
        divisions_by_grade.setdefault(g, set()).add(d or "")
    
    # Convert sets -> sorted lists for JSON serialization.
    divisions_by_grade = {
        g: sorted(list(ds), key=lambda x: (division_rank.get(x, 999), str(x)))
        for g, ds in divisions_by_grade.items()
    }

    if request.method == "POST":
        student_form = AddStudentForm(request.POST, organization=org, initial=initial)
        screening_form = NewScreeningForm(request.POST, student=None, organization=org)

        if student_form.is_valid() and screening_form.is_valid():
            try:
                with transaction.atomic():
                    grade = student_form.cleaned_data["grade"]
                    division = student_form.cleaned_data["division"] or ""
                    classroom = Classroom.objects.filter(organization=org, grade=grade, division=division).first()
                    if not classroom:
                        raise ValidationError("Selected Grade/Division does not exist.")

                    phone = screening_form.cleaned_data["parent_phone_e164"]
                    guardian, _ = Guardian.objects.get_or_create(
                        organization=org, phone_e164=phone,
                        defaults={"full_name": "Parent", "whatsapp_opt_in": True}
                    )

                    answers = screening_form.cleaned_data["answers"]
                    derived = screening_form.cleaned_data["_derived"]

                    student = Student.objects.create(
                        organization=org,
                        classroom=classroom,
                        first_name=(answers.get("student_name") or "").strip(),
                        last_name="",
                        gender=answers.get("sex"),
                        dob=screening_form.cleaned_data.get("dob"),
                        is_low_income=student_form.cleaned_data.get("is_low_income", False),
                        student_code=answers.get("unique_student_id"),
                        primary_guardian=guardian,
                    )

                    now_dt = timezone.now()
                    height_cm = float(derived["height_cm"])
                    weight_kg = float(derived["weight_kg"])

                    s = Screening(
                        organization=org,
                        student=student,
                        teacher=_teacher_fk(request),
                        screened_at=now_dt,
                        gender=student.gender,
                        age_years=derived["age_years"],
                        age_months=derived["age_months"],
                        height_cm=height_cm,
                        weight_kg=weight_kg,
                        muac_cm=derived.get("muac_cm"),
                        answers=answers,
                        is_low_income_at_screen=student_form.cleaned_data.get("is_low_income", False),
                    )

                    rr = compute_risk(
                        age_years=float(derived["age_years"]),
                        age_months=int(derived["age_months"]),
                        sex=student.gender,
                        height_cm=height_cm,
                        weight_kg=weight_kg,
                        muac_cm=float(derived["muac_cm"]) if derived.get("muac_cm") is not None else None,
                        answers=answers,
                    )
                    s.risk_level = rr.level
                    s.red_flags = rr.flags
                    if rr.derived.get("bmi") is not None:
                        s.bmi = rr.derived["bmi"]
                    if rr.derived.get("baz") is not None:
                        s.baz = rr.derived["baz"]
                    s.save()

                log = _auto_send_for_screening(request, s)
                messages.success(request, f"Student “{student.full_name}” created and screening completed.")
                dashboard_url = reverse("screening_only:teacher_dashboard")
                if log:
                    preview = reverse("whatsapp_preview", args=[log.id]) + f"?next={dashboard_url}"
                    return redirect(preview)
                return redirect(dashboard_url)

            except (IntegrityError, ValidationError, ValueError) as e:
                messages.error(request, f"Could not complete: {e}")

    else:
        student_form = AddStudentForm(organization=org, initial=initial)
        screening_form = NewScreeningForm(student=None, organization=org)

    return render(request, "screening/add_student.html", {
        "student_form": student_form,
        "screening_form": screening_form,
        "divisions_by_grade": json.dumps(divisions_by_grade),
    })
