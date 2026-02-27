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

from roster.pid import compute_pid
from django.http import HttpResponse
import json as _json

def teacher_portal_token(request, token: str):
    # First, resolve the organization from the slug token
    org = get_object_or_404(Organization, screening_link_token=token)

    # If this is a Screening Program school, send them into the screening_only teacher flow
    try:
        # Will raise if no screening_only_profile
        _ = org.screening_only_profile
        return redirect(
            reverse("screening_only:teacher_access_portal", args=[org.screening_link_token])
        )
    except Exception:
        # Not a Screening Program school → fall back to legacy teacher portal
        pass

    # Legacy / non-screening-only org: use the standard teacher portal
    request.session["public_teacher_org_id"] = org.id
    request.org = org
    if request.user.is_authenticated:
        request.membership = OrgMembership.objects.filter(
            user=request.user, organization=org, is_active=True
        ).first()
    return teacher_portal(request)

def _teacher_fk(request):
    return request.user if getattr(request.user, "is_authenticated", False) else None

def _open_in_new_tab_then_redirect(*, wa_url: str, redirect_url: str) -> HttpResponse:
    """
    Returns an HTML page with a modal that says "Open WhatsApp". When the user
    clicks the button, window.open() is user-triggered so it is not blocked.
    """
    wa_js = _json.dumps(wa_url)
    next_js = _json.dumps(redirect_url)
    # Escape for use in HTML attributes if needed (wa_url is already in JS)
    wa_escaped = wa_url.replace("'", "&#39;").replace('"', "&quot;")
    redirect_escaped = redirect_url.replace("'", "&#39;").replace('"', "&quot;")

    html = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Screening complete</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, sans-serif; background: #fafafa; min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
    .modal-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; padding: 20px; box-sizing: border-box; }}
    .modal {{ background: #fff; border-radius: 12px; padding: 24px; max-width: 380px; box-shadow: 0 8px 32px rgba(0,0,0,0.15); text-align: center; }}
    .modal h2 {{ margin: 0 0 12px 0; font-size: 1.25rem; color: #111; }}
    .modal p {{ margin: 0 0 20px 0; color: #555; font-size: 0.95rem; line-height: 1.4; }}
    .modal .buttons {{ display: flex; flex-direction: column; gap: 10px; }}
    .modal .btn {{ display: inline-block; padding: 12px 20px; border-radius: 8px; font-size: 1rem; font-weight: 500; text-decoration: none; border: none; cursor: pointer; transition: background 0.15s; }}
    .modal .btn-whatsapp {{ background: #000; color: #fff; }}
    .modal .btn-whatsapp:hover {{ opacity: 0.9; }}
    .modal .btn-dashboard {{ background: #f3f4f6; color: #374151; }}
    .modal .btn-dashboard:hover {{ background: #e5e7eb; }}
  </style>
  </head>
  <body>
    <div class="modal-overlay" role="dialog" aria-labelledby="modal-title" aria-modal="true">
      <div class="modal">
        <h2 id="modal-title">Screening complete</h2>
        <p>Open WhatsApp to send the message to the parent, then go to the dashboard.</p>
        <div class="buttons">
          <button type="button" class="btn btn-whatsapp" id="open-whatsapp">Open WhatsApp</button>
          <a href="{redirect_escaped}" class="btn btn-dashboard" id="go-dashboard">Go to dashboard</a>
        </div>
      </div>
    </div>
    <script>
      (function () {{
        var waUrl = {wa_js};
        var redirectUrl = {next_js};
        var openBtn = document.getElementById("open-whatsapp");
        var dashboardLink = document.getElementById("go-dashboard");
        openBtn.addEventListener("click", function () {{
          try {{
            window.open(waUrl, "_blank", "noopener");
            window.location.href = redirectUrl;
          }} catch (e) {{
            console.error("[NutriLift] window.open error:", e);
          }}
        }});
      }})();
    </script>
    <noscript>
      <p style="padding: 20px; text-align: center;">
        <a href="{wa_escaped}" target="_blank" rel="noopener">Open WhatsApp</a> &middot;
        <a href="{redirect_escaped}">Go to dashboard</a>
      </p>
    </noscript>
  </body>
</html>"""
    return HttpResponse(html)

def _prepare_parent_whatsapp_url(request, s, *, parent_phone_e164: str) -> str | None:
    """
    Builds the WhatsApp click-to-chat URL immediately (no preview page).
    Also creates a MessageLog WITHOUT phone/payload (stores only pid + metadata).
    """
    phone = (parent_phone_e164 or "").strip()
    if not phone:
        messages.warning(request, "No parent phone number provided; cannot open WhatsApp.")
        return None

    try:
        # Screening-only orgs
        try:
            s.organization.screening_only_profile
            is_screening_only = True
        except Exception:
            is_screening_only = False

        if is_screening_only:
            # In Screening Program, only RED sends parent WhatsApp
            if s.risk_level != "RED":
                return None

            from screening_only.services import prepare_screening_only_redflag_click_to_chat
            form_language = (request.POST.get("form_language") or request.GET.get("lang") or "").strip()
            qa_text = (request.POST.get("wa_questions_and_answers") or "").strip()

            _log, wa_url = prepare_screening_only_redflag_click_to_chat(
                request,
                s,
                form_language=form_language,
                questions_and_answers=qa_text,
                to_phone_e164=phone,
            )
            return wa_url or None

        # Standard orgs
        from messaging.services import prepare_screening_status_click_to_chat
        _log, wa_url = prepare_screening_status_click_to_chat(s, to_phone_e164=phone)
        return wa_url or None

    except RateLimitExceeded as e:
        messages.error(request, str(e))
        return None
    except Exception:
        logger.exception("WhatsApp URL preparation failed")
        messages.error(request, "Could not open WhatsApp.")
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
            .filter(organization=org, pid=OuterRef("pid"))
            .order_by("-screened_at")
            .values("risk_level")[:1]
    )

    approved_application = (
        Application.objects
        .filter(
            organization=org,
            pid=OuterRef("pid"),
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
        students = students.order_by("classroom__grade", "classroom__division", "student_code", "pid")

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
    prev = Screening.objects.filter(
        organization=student.organization,
        pid=student.pid,
        screened_at__gte=now_dt - timedelta(days=183),
    ).order_by("-screened_at").first()

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
            pid = student.pid

            # Legacy fallback: if an old student exists without pid, try to compute it once.
            if not pid:
                try:
                    pid = compute_pid(
                        first_name=(student.first_name or ""),
                        phone_e164=form.cleaned_data["parent_phone_e164"],
                    )
                    student.pid = pid
                    student.save(update_fields=["pid", "updated_at"])
                except Exception:
                    pid = None

            guardian = None
            if pid:
                guardian, _ = Guardian.objects.get_or_create(
                    organization=org,
                    pid=pid,
                    defaults={
                        "full_name": None,
                        "phone_e164": None,
                        "whatsapp_opt_in": True,
                    },
                )
                if student.primary_guardian_id != guardian.id:
                    student.primary_guardian = guardian
                    student.save(update_fields=["primary_guardian", "updated_at"])

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
                pid=pid,  # NEW
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

            parent_phone = form.cleaned_data.get("parent_phone_e164") or ""
            dashboard_url = reverse("screening_only:teacher_dashboard")

            parent_phone = (form.cleaned_data.get("parent_phone_e164") or "").strip()
            wa_url = _prepare_parent_whatsapp_url(request, s, parent_phone_e164=parent_phone)

            if wa_url:
                return _open_in_new_tab_then_redirect(wa_url=wa_url, redirect_url=dashboard_url)

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
    dashboard_url = reverse("screening_only:teacher_dashboard")

    # Since we do not store phone numbers, the caller must provide it
    phone = (request.GET.get("phone_e164") or request.POST.get("phone_e164") or "").strip()
    if not phone:
        messages.error(request, "Parent phone is not stored. Please enter the phone number to open WhatsApp.")
        return redirect(dashboard_url)

    wa_url = _prepare_parent_whatsapp_url(request, s, parent_phone_e164=phone)
    if not wa_url:
        return redirect(dashboard_url)

    # This redirect will be opened in a new tab if the link/form uses target="_blank"
    return redirect(wa_url)


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

                    # --- Compute PID from transient form inputs (DO NOT STORE these values) ---
                    # Support both naming conventions:
                    #   - your prompt: first_name, phone_e164
                    #   - current codebase: student_name, parent_phone_e164
                    raw_first_name = (request.POST.get("first_name") or request.POST.get("student_name") or "").strip()

                    # phone comes from cleaned_data so it is normalized to E.164
                    phone_e164 = (
                        screening_form.cleaned_data.get("phone_e164")
                        or screening_form.cleaned_data.get("parent_phone_e164")
                    )

                    pid = compute_pid(first_name=raw_first_name, phone_e164=phone_e164)

                    answers = screening_form.cleaned_data["answers"]     # already PII-free after Step 4
                    derived = screening_form.cleaned_data["_derived"]

                    # --- Upsert Student by PID (within this organization) ---
                    student = Student.objects.filter(organization=org, pid=pid).first()

                    if student is None:
                        # Create placeholder guardian row keyed by PID (no name, no phone stored)
                        guardian, _ = Guardian.objects.get_or_create(
                            organization=org,
                            pid=pid,
                            defaults={
                                "full_name": None,
                                "phone_e164": None,
                                "whatsapp_opt_in": True,
                            },
                        )

                        # Create placeholder student row keyed by PID (no name stored)
                        student = Student.objects.create(
                            organization=org,
                            classroom=classroom,
                            pid=pid,
                            first_name=None,
                            last_name=None,
                            gender=answers.get("sex"),
                            dob=screening_form.cleaned_data.get("dob"),
                            is_low_income=student_form.cleaned_data.get("is_low_income", False),
                            student_code=answers.get("unique_student_id"),
                            primary_guardian=guardian,
                        )
                    else:
                        # Ensure guardian row exists (PID-keyed)
                        guardian, _ = Guardian.objects.get_or_create(
                            organization=org,
                            pid=pid,
                            defaults={
                                "full_name": None,
                                "phone_e164": None,
                                "whatsapp_opt_in": True,
                            },
                        )

                        # Optional: keep student up-to-date without storing PII
                        update_fields = []
                        if student.classroom_id != classroom.id:
                            student.classroom = classroom
                            update_fields.append("classroom")

                        #    Keep non-PII master data updated
                        new_code = answers.get("unique_student_id")
                        if new_code and student.student_code != new_code:
                            student.student_code = new_code
                            update_fields.append("student_code")

                        new_dob = screening_form.cleaned_data.get("dob")
                        if new_dob and student.dob != new_dob:
                            student.dob = new_dob
                            update_fields.append("dob")

                        new_gender = answers.get("sex")
                        if new_gender and student.gender != new_gender:
                            student.gender = new_gender
                            update_fields.append("gender")

                        new_low_income = student_form.cleaned_data.get("is_low_income", False)
                        if getattr(student, "is_low_income", False) != new_low_income:
                            student.is_low_income = new_low_income
                            update_fields.append("is_low_income")

                        if student.primary_guardian_id != guardian.id:
                            student.primary_guardian = guardian
                            update_fields.append("primary_guardian")

                        if update_fields:
                            student.save(update_fields=update_fields + ["updated_at"])

                    # --- Create Screening record linked by PID ---
                    now_dt = timezone.now()
                    height_cm = float(derived["height_cm"])
                    weight_kg = float(derived["weight_kg"])

                    s = Screening(
                        organization=org,
                        student=student,                 # kept for compatibility, but linkage is PID
                        pid=pid,                         # NEW linkage field
                        teacher=_teacher_fk(request),
                        screened_at=now_dt,
                        gender=student.gender,
                        age_years=derived["age_years"],
                        age_months=derived["age_months"],
                        height_cm=height_cm,
                        weight_kg=weight_kg,
                        muac_cm=derived.get("muac_cm"),
                        answers=answers,                 # PII-free JSON
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


                parent_phone = screening_form.cleaned_data.get("parent_phone_e164") or ""
                dashboard_url = reverse("screening_only:teacher_dashboard")

                parent_phone = (screening_form.cleaned_data.get("parent_phone_e164") or "").strip()
                wa_url = _prepare_parent_whatsapp_url(request, s, parent_phone_e164=parent_phone)

                messages.success(request, "Student created and screening completed.")

                if wa_url:
                    return _open_in_new_tab_then_redirect(wa_url=wa_url, redirect_url=dashboard_url)

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
