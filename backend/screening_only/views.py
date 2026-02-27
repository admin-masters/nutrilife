from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.http import HttpResponseForbidden, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from messaging.i18n import flags_to_text
from accounts.models import Organization, OrgMembership, Role
from roster.models import Classroom, Student
from screening.models import Screening
from django.db.models import OuterRef, Subquery, Q
from .decorators import require_screening_only_admin, require_screening_only_teacher
from .forms import SchoolEnrollmentForm, TeacherAccessForm
from .google_oauth import (
    GoogleOAuthError,
    build_authorization_url,
    exchange_code_for_id_token,
    generate_state,
    verify_id_token_and_get_email,
)
from .models import ScreeningSchoolProfile, ScreeningTermsAcceptance
from .services import (
    TERMS_VERSION,
    academic_year_range,
    available_academic_years,
    screening_counts_by_class,
    unique_screening_token,
    parse_parent_token,
)
from .teacher_terms_content import DEFAULT_LANG, LANG_OPTIONS, TERMS_BY_LANG

# Session key used to remember teacher's currently selected class/section (Classroom.id)
TEACHER_SELECTED_CLASSROOM_SESSION_KEY = "sp_teacher_selected_classroom_id"

User = get_user_model()


def _split_full_name(full_name: str) -> tuple[str, str]:
    full_name = (full_name or "").strip()
    if not full_name:
        return "", ""
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _ensure_membership(user, org: Organization, role: str) -> OrgMembership:
    mem, _created = OrgMembership.objects.get_or_create(
        user=user,
        organization=org,
        role=role,
        defaults={"is_active": True},
    )
    if not mem.is_active:
        mem.is_active = True
        mem.save(update_fields=["is_active"])
    return mem


def _is_terms_accepted(user, org: Organization, actor_role: str) -> bool:
    return ScreeningTermsAcceptance.objects.filter(
        user=user,
        organization=org,
        actor_role=actor_role,
        version=TERMS_VERSION,
    ).exists()


def enroll_school(request: HttpRequest) -> HttpResponse:
    """
    Public enrollment link common for all schools:contentReference[oaicite:10]{index=10}.
    Creates Organization + ScreeningSchoolProfile.
    """
    if request.method == "POST":
        form = SchoolEnrollmentForm(request.POST)
        if form.is_valid():
            token = unique_screening_token(form.cleaned_data["school_name"])

            org = Organization.objects.create(
                name=form.cleaned_data["school_name"],
                org_type="SCHOOL",
                city=form.cleaned_data.get("city") or "",
                state=form.cleaned_data.get("state") or "",
                country=form.cleaned_data.get("country") or "India",
                screening_link_token=token,
            )
            ScreeningSchoolProfile.objects.create(
                organization=org,
                district=form.cleaned_data.get("district") or "",
                address=form.cleaned_data.get("address") or "",
                principal_name=form.cleaned_data.get("principal_name") or "",
                principal_email=form.cleaned_data["principal_email"],
                operator_name=form.cleaned_data.get("operator_name") or "",
                operator_email=form.cleaned_data.get("operator_email") or "",
                local_language_code=form.cleaned_data.get("local_language_code") or "",
            )

            messages.success(request, "School registered. Next: sign in with your authorized Google account.")
            return redirect("screening_only:admin_auth_required", token=org.screening_link_token)
    else:
        form = SchoolEnrollmentForm()

    return render(request, "screening_only/enroll_school.html", {"form": form})


def enroll_success(request: HttpRequest, token: str) -> HttpResponse:
    org = get_object_or_404(Organization, screening_link_token=token)
    try:
        org.screening_only_profile
    except Exception:
        return HttpResponseForbidden("Not a Screening Program school.")

    admin_auth_url = reverse("screening_only:admin_auth_required", args=[token])
    return render(
        request,
        "screening_only/enroll_success.html",
        {
            "org": org,
            "admin_auth_url": admin_auth_url,
        },
    )


def admin_auth_required(request: HttpRequest, token: str) -> HttpResponse:
    """
    Prompts admin to sign in with registered Google account:contentReference[oaicite:11]{index=11}.
    """
    org = get_object_or_404(Organization, screening_link_token=token)
    profile = getattr(org, "screening_only_profile", None)
    if not profile:
        return HttpResponseForbidden("This school is not enrolled in the Screening Program.")

    # Store pending OAuth context in session
    request.session["sp_oauth_role"] = "admin"
    request.session["sp_oauth_org_id"] = org.id
    request.session.modified = True

    return render(
        request,
        "screening_only/admin_auth_required.html",
        {
            "org": org,
            "principal_email": profile.principal_email,
            "operator_email": profile.operator_email,
            "google_start_url": reverse("screening_only:google_oauth_start"),
        },
    )


def teacher_access_portal(request: HttpRequest, token: str) -> HttpResponse:
    """
    Teacher enters name + email, accepts T&C, then signs in with Google using the SAME email:contentReference[oaicite:12]{index=12}.
    """
    org = get_object_or_404(Organization, screening_link_token=token)
    profile = getattr(org, "screening_only_profile", None)
    if not profile:
        return HttpResponseForbidden("This school is not enrolled in the Screening Program.")

    if request.method == "POST":
        form = TeacherAccessForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].strip().lower()
            full_name = form.cleaned_data["full_name"].strip()

            request.session["sp_oauth_role"] = "teacher"
            request.session["sp_oauth_org_id"] = org.id
            request.session["sp_teacher_email"] = email
            request.session["sp_teacher_full_name"] = full_name
            request.session["sp_teacher_terms_ok"] = True
            request.session.modified = True

            return redirect("screening_only:teacher_auth_required")
    else:
        form = TeacherAccessForm()

    return render(
        request,
        "screening_only/teacher_access_portal.html",
        {
            "org": org,
            "form": form,
        },
    )

def teacher_terms(request: HttpRequest) -> HttpResponse:
    """
    Public Terms & Conditions page for teachers.
    Default language is Marathi. Language switches via ?lang=<code> (full page refresh).
    """
    lang = (request.GET.get("lang") or DEFAULT_LANG).strip().lower()
    if lang not in TERMS_BY_LANG:
        lang = DEFAULT_LANG
    return_token = request.GET.get("return_token", "").strip()
    return render(
        request,
        "screening_only/teacher_terms.html",
        {
            "lang": lang,
            "languages": LANG_OPTIONS,
            "terms_paragraphs": TERMS_BY_LANG[lang],
            "return_token": return_token,
        },
    )

def teacher_auth_required(request: HttpRequest) -> HttpResponse:
    """
    Separate screen: “Sign in with Google”, reminds teacher to use the correct email:contentReference[oaicite:13]{index=13}.
    """
    role = request.session.get("sp_oauth_role")
    org_id = request.session.get("sp_oauth_org_id")
    expected = request.session.get("sp_teacher_email")
    if role != "teacher" or not org_id or not expected:
        messages.error(request, "Teacher access session expired. Please open the teacher link again.")
        return redirect("screening_only:enroll_school")

    org = get_object_or_404(Organization, id=org_id)
    return render(
        request,
        "screening_only/teacher_auth_required.html",
        {
            "org": org,
            "expected_email": expected,
            "google_start_url": reverse("screening_only:google_oauth_start"),
        },
    )

@require_screening_only_teacher
def teacher_onboarding(request: HttpRequest) -> HttpResponse:
    """
    Teacher onboarding: show guide/training, then continue to dashboard.
    """
    org = request.org  # set by the decorator/middleware
    guide_url = getattr(settings, "SCREENING_GUIDE_URL", "") or "#"
    training_url = getattr(settings, "SCREENING_TRAINING_VIDEO_URL", "") or "#"
    continue_url = reverse("screening_only:teacher_class_selection")

    return render(
        request,
        "screening_only/admin_onboarding.html",
        {
            "org": org,
            "guide_url": guide_url,
            "training_url": training_url,
            "continue_url": continue_url,
        },
    )


def google_oauth_start(request: HttpRequest) -> HttpResponse:
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", None) or ""
    if not client_id:
        return HttpResponseForbidden("GOOGLE_OAUTH_CLIENT_ID is not configured.")

    state = generate_state()
    request.session["sp_oauth_state"] = state
    request.session.modified = True

    redirect_uri = request.build_absolute_uri(reverse("screening_only:google_oauth_callback"))
    url = build_authorization_url(client_id=client_id, redirect_uri=redirect_uri, state=state)
    return redirect(url)

def _redirect_teacher_or_enroll(request):
    """
    If a teacher is already logged in and we know their org, redirect them
    to the teacher login URL with slug (screening teacher portal).
    Otherwise, fall back to the enrollment page.
    """
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        org_id = request.session.get("current_org_id")
        if org_id:
            # Ensure this user is a TEACHER (not only admin) for this org
            has_teacher_role = OrgMembership.objects.filter(
                user=user,
                organization_id=org_id,
                role=Role.TEACHER,
                is_active=True,
            ).exists()
            if has_teacher_role:
                try:
                    org = Organization.objects.get(id=org_id)
                    # This name is from backend/screening/urls.py
                    teacher_url = reverse("teacher_portal_token", args=[org.screening_link_token])
                    return redirect(teacher_url)
                except Organization.DoesNotExist:
                    pass

    # Fallback: original behavior
    return redirect("screening_only:enroll_school")

def google_oauth_callback(request: HttpRequest) -> HttpResponse:
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", None) or ""
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", None) or ""

    if not client_id or not client_secret:
        return HttpResponseForbidden("Google OAuth is not configured (missing client id/secret).")

    state = request.GET.get("state") or ""
    code = request.GET.get("code") or ""
    expected_state = request.session.get("sp_oauth_state") or ""

    if not code or not state or state != expected_state:
        messages.error(request, "Invalid login session. Please try again.")
        return _redirect_teacher_or_enroll(request)

    role = request.session.get("sp_oauth_role")
    
    # For existing_admin, we don't have org_id yet - we'll find it after OAuth
    # For other roles (admin, teacher), we need org_id
    if role != "existing_admin":
        org_id = request.session.get("sp_oauth_org_id")
        if not role or not org_id:
            messages.error(request, "Login session expired. Please start again.")
            return _redirect_teacher_or_enroll(request)
        org = get_object_or_404(Organization, id=org_id)
    
    redirect_uri = request.build_absolute_uri(reverse("screening_only:google_oauth_callback"))

    try:
        id_token = exchange_code_for_id_token(code=code, client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
        token_info = verify_id_token_and_get_email(id_token=id_token, client_id=client_id)
    except GoogleOAuthError as e:
            messages.error(request, f"Google sign-in failed: {e}")
            return _redirect_teacher_or_enroll(request)

    email = (token_info.get("email") or "").strip().lower()

    # Handle existing admin login FIRST (before other role checks)
    if role == "existing_admin":
        # Find organization by matching email to principal_email or operator_email
        from .models import ScreeningSchoolProfile
        
        # Find the organization where this email is authorized
        profile = ScreeningSchoolProfile.objects.filter(
            Q(principal_email__iexact=email) | Q(operator_email__iexact=email)
        ).select_related("organization").first()
        
        if not profile:
            messages.error(
                request, 
                f"No school found for email {email}. Please register your school first."
            )
            return redirect("screening_only:enroll_school")
        
        org = profile.organization
        
        # Get or create user
        user, created = User.objects.get_or_create(email=email, defaults={"is_active": True})
        if created:
            user.set_unusable_password()
            user.save()
        
        # Check if membership already exists - don't create duplicate
        existing_membership = OrgMembership.objects.filter(
            user=user, 
            organization=org, 
            role=Role.ORG_ADMIN
        ).first()
    
        if existing_membership:
            # Membership exists, just activate if inactive
            if not existing_membership.is_active:
                existing_membership.is_active = True
                existing_membership.save(update_fields=["is_active"])
        else:
            # Create membership only if it doesn't exist
            _ensure_membership(user, org, Role.ORG_ADMIN)
        
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["current_org_id"] = org.id
        
        # Clear OAuth session
        for k in ["sp_oauth_state", "sp_oauth_role", "sp_oauth_org_id"]:
            request.session.pop(k, None)
        
        # Redirect directly to admin link dashboard (not onboarding)
        return redirect("screening_only:admin_link_dashboard")
    # Admin authorization: only registered principal/operator emails may login:contentReference[oaicite:14]{index=14}.
    if role == "admin":
        profile: Optional[ScreeningSchoolProfile] = getattr(org, "screening_only_profile", None)
        if not profile:
            return HttpResponseForbidden("This school is not enrolled in the Screening Program.")
        if not profile.is_authorized_admin_email(email):
            return render(
                request,
                "screening_only/admin_unauthorized.html",
                {
                    "org": org,
                    "attempted_email": email,
                    "principal_email": profile.principal_email,
                    "operator_email": profile.operator_email,
                    "retry_url": reverse("screening_only:admin_auth_required", args=[org.screening_link_token]),
                },
            )

        user, created = User.objects.get_or_create(email=email, defaults={"is_active": True})
        if created:
            user.set_unusable_password()
            user.save()

        _ensure_membership(user, org, Role.ORG_ADMIN)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["current_org_id"] = org.id

        # clear oauth session
        for k in ["sp_oauth_state", "sp_oauth_role", "sp_oauth_org_id"]:   
            request.session.pop(k, None)
          # Auto-accept terms and mark onboarding as completed
        if not _is_terms_accepted(user, org, ScreeningTermsAcceptance.ActorRole.ORG_ADMIN):
            ScreeningTermsAcceptance.objects.create(
                organization=org,
                user=user,
                actor_role=ScreeningTermsAcceptance.ActorRole.ORG_ADMIN,
                version=TERMS_VERSION,
                ip_address=_get_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
            )
  
        # Mark onboarding as completed
        try:
            prof = org.screening_only_profile
            if not prof.onboarding_completed_at:
                prof.onboarding_completed_at = timezone.now()
                prof.save(update_fields=["onboarding_completed_at"])
        except Exception:
            pass
        return redirect("screening_only:admin_link_dashboard")

    # Teacher authorization: logged-in email must match entered email:contentReference[oaicite:15]{index=15}.
    if role == "teacher":
        expected = (request.session.get("sp_teacher_email") or "").strip().lower()
        full_name = (request.session.get("sp_teacher_full_name") or "").strip()

        if not expected or email != expected:
            return render(
                request,
                "screening_only/teacher_access_denied.html",
                {
                    "org": org,
                    "expected_email": expected,
                    "attempted_email": email,
                    "retry_url": reverse("screening_only:teacher_auth_required"),
                    "change_email_url": reverse("screening_only:teacher_access_portal", args=[org.screening_link_token]),
                },
            )

        user, created = User.objects.get_or_create(email=email, defaults={"is_active": True})
        if created:
            user.set_unusable_password()

        fn, ln = _split_full_name(full_name)
        if fn and not user.first_name:
            user.first_name = fn
        if ln and not user.last_name:
            user.last_name = ln
        user.save()

        existing_memberships = OrgMembership.objects.filter(
            user=user,
            is_active=True
        ).select_related("organization")

        allowed_for_teacher_flow = [Role.TEACHER, Role.ORG_ADMIN]
        # Check if user has NON-TEACHER roles (and no TEACHER role)
        non_teacher_memberships = existing_memberships.exclude(role__in=allowed_for_teacher_flow)
        teacher_memberships = existing_memberships.filter(role=Role.TEACHER)

        if non_teacher_memberships.exists() and not teacher_memberships.exists():
            other_orgs = [mem.organization.name for mem in non_teacher_memberships]
            other_roles = [mem.role for mem in non_teacher_memberships]
            return render(
                request,
                "screening_only/teacher_access_denied.html",  # You may want to create a new template for this
                {
                    "org": org,
                    "expected_email": expected,
                    "attempted_email": email,
                    "error_message": f"This email is already registered with other organization(s) ({', '.join(other_orgs)}) with role(s): {', '.join(set(other_roles))}. "
                                     f"Teachers cannot use an email that is registered with a different role. Please use a different email address.",
                    "retry_url": reverse("screening_only:teacher_auth_required"),
                    "change_email_url": reverse("screening_only:teacher_access_portal", args=[org.screening_link_token]),
                },
            )
        # other_org_memberships = existing_memberships.exclude(organization=org).select_related("organization")
        current_org_memberships = existing_memberships.filter(organization=org)
        other_org_memberships = existing_memberships.exclude(organization=org).select_related("organization")
        if other_org_memberships.exists():
            other_orgs = [mem.organization.name for mem in other_org_memberships]
            messages.warning(
                request,
                f"This email is already registered with other organization(s): {', '.join(other_orgs)}. "
                f"You are now also registered as a teacher for {org.name}."
            ) 
        # Ensure membership for this organization as teacher
        if not current_org_memberships.exists():
            _ensure_membership(user, org, Role.TEACHER)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["current_org_id"] = org.id

        # record teacher terms acceptance (they checked accept_terms in step 1)
        if request.session.get("sp_teacher_terms_ok") and not _is_terms_accepted(user, org, ScreeningTermsAcceptance.ActorRole.TEACHER):
            ScreeningTermsAcceptance.objects.create(
                organization=org,
                user=user,
                actor_role=ScreeningTermsAcceptance.ActorRole.TEACHER,
                version=TERMS_VERSION,
                ip_address=_get_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
            )

        # clear oauth session
        for k in ["sp_oauth_state", "sp_oauth_role", "sp_oauth_org_id", "sp_teacher_email", "sp_teacher_full_name", "sp_teacher_terms_ok"]:
            request.session.pop(k, None)

        return redirect("screening_only:teacher_onboarding")      
        

    messages.error(request, "Unknown login flow.")
    return _redirect_teacher_or_enroll(request)


def _get_ip(request: HttpRequest) -> Optional[str]:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # take first
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@require_screening_only_admin
def admin_onboarding(request: HttpRequest) -> HttpResponse:
    """
    Admin onboarding includes acceptance (one-time) and moves to link sharing dashboard:contentReference[oaicite:16]{index=16}.
    """
    org = request.org
    user = request.user

    accepted = _is_terms_accepted(user, org, ScreeningTermsAcceptance.ActorRole.ORG_ADMIN)
    if request.method == "POST":
        if request.POST.get("accept_terms") == "on":
            if not accepted:
                ScreeningTermsAcceptance.objects.create(
                    organization=org,
                    user=user,
                    actor_role=ScreeningTermsAcceptance.ActorRole.ORG_ADMIN,
                    version=TERMS_VERSION,
                    ip_address=_get_ip(request),
                    user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
                )
            try:
                prof = org.screening_only_profile
                if not prof.onboarding_completed_at:
                    prof.onboarding_completed_at = timezone.now()
                    prof.save(update_fields=["onboarding_completed_at"])
            except Exception:
                pass

            return redirect("screening_only:admin_link_dashboard")
        messages.error(request, "You must accept the terms to continue.")

    guide_url = getattr(settings, "SCREENING_GUIDE_URL", "")
    training_url = getattr(settings, "SCREENING_TRAINING_VIDEO_URL", "")
    terms_url = getattr(settings, "SCREENING_TERMS_URL", "") or "#"

    return render(
        request,
        "screening_only/admin_onboarding.html",
        {
            "org": org,
            "accepted": accepted,
            "guide_url": guide_url,
            "training_url": training_url,
            "terms_url": terms_url,
        },
    )


@require_screening_only_admin
def admin_link_dashboard(request: HttpRequest) -> HttpResponse:
    """
    Admin sees pre-written teacher message and screening link to share:contentReference[oaicite:17]{index=17}.
    """
    org = request.org
    teacher_link = request.build_absolute_uri(reverse("screening_only:teacher_access_portal", args=[org.screening_link_token]))

    # You can tweak this content to exactly match your final comms.
    teacher_message = (
        f"Dear Teacher,\n\n"
        f"Our school is participating in the Nutrilift Growth & Nutrition Screening program.\n"
        f"Please use the link below to complete student screenings as per the schedule shared by the school.\n\n"
        f"Screening link: {teacher_link}\n\n"
        f"Thank you."
    )

    return render(
        request,
        "screening_only/admin_link_dashboard.html",
        {
            "org": org,
            "teacher_link": teacher_link,
            "teacher_message": teacher_message,
            "dashboard_url": reverse("screening_only:admin_performance_dashboard"),
        },
    )


@require_screening_only_admin
def admin_performance_dashboard(request: HttpRequest) -> HttpResponse:
    """
    Shows screening performance by class/division and academic year (once/twice):contentReference[oaicite:18]{index=18}.
    """
    org = request.org
    ay = request.GET.get("ay") or ""
    years = available_academic_years(org)
    if not ay:
        ay = years[0] if years else ""

    start_dt, end_dt = academic_year_range(ay)
    rows = screening_counts_by_class(org, start_dt, end_dt)

    return render(
        request,
        "screening_only/admin_performance_dashboard.html",
        {
            "org": org,
            "ay": ay,
            "years": years,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "rows": rows,
            "link_dashboard_url": reverse("screening_only:admin_link_dashboard"),
        },
    )

@require_screening_only_teacher
def teacher_class_selection(request: HttpRequest) -> HttpResponse:
    """
    Mandatory class/section selection page for teachers (stores selection in session).
    """
    import json

    org = request.org
    classrooms_qs = Classroom.objects.filter(organization=org).order_by("grade", "division", "id")

    # Build divisions-by-grade mapping (for dependent dropdown)
    preferred_grade_order = ["Nursery", "K.G."] + [str(i) for i in range(1, 13)] + ["Other"]
    grade_rank = {g: i for i, g in enumerate(preferred_grade_order)}

    preferred_division_order = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + ["Other"]
    division_rank = {d: i for i, d in enumerate(preferred_division_order)}

    divisions_by_grade = {}
    for c in classrooms_qs:
        g = c.grade or ""
        d = c.division or ""
        divisions_by_grade.setdefault(g, set()).add(d)

    # Sorted grades + sorted divisions per grade
    grades = sorted(divisions_by_grade.keys(), key=lambda g: (grade_rank.get(g, 999), str(g)))
    divisions_by_grade_sorted = {}
    for g in grades:
        divs = sorted(list(divisions_by_grade[g]), key=lambda d: (division_rank.get(d, 999), str(d)))
        divisions_by_grade_sorted[g] = divs

    # Default selection from session (if any)
    selected_grade = ""
    selected_division = ""
    selected_classroom_id = request.session.get(TEACHER_SELECTED_CLASSROOM_SESSION_KEY) or ""
    if selected_classroom_id:
        selected_classroom = classrooms_qs.filter(id=selected_classroom_id).first()
        if selected_classroom:
            selected_grade = selected_classroom.grade or ""
            selected_division = selected_classroom.division or ""
        else:
            # stale/invalid stored selection
            request.session.pop(TEACHER_SELECTED_CLASSROOM_SESSION_KEY, None)

    if request.method == "POST":
        grade = (request.POST.get("grade") or "").strip()
        division = (request.POST.get("division") or "").strip()

        classroom = Classroom.objects.filter(
            organization=org,
            grade=grade,
            division=division,
        ).first()

        if not classroom:
            messages.error(request, "Please select a valid Class and Section.")
            selected_grade = grade
            selected_division = division
        else:
            request.session[TEACHER_SELECTED_CLASSROOM_SESSION_KEY] = str(classroom.id)
            return redirect("screening_only:teacher_dashboard")

    return render(
        request,
        "screening_only/teacher_class_selection.html",
        {
            "org": org,
            "grades": grades,
            "divisions_by_grade": json.dumps(divisions_by_grade_sorted),
            "selected_grade": selected_grade,
            "selected_division": selected_division,
        },
    )

@require_screening_only_teacher
def teacher_dashboard(request: HttpRequest) -> HttpResponse:
    """
    Teacher dashboard: must have a selected class/section in session, then shows only those students.
    """
    org = request.org
    # Basic cycle concept: last 6 months
    cycle_start = timezone.now() - timedelta(days=183)

    classrooms = Classroom.objects.filter(organization=org).order_by("grade", "division")

    # NEW: enforce mandatory selection from session
    classroom_id = request.session.get(TEACHER_SELECTED_CLASSROOM_SESSION_KEY) or ""
    selected_classroom = classrooms.filter(id=classroom_id).first() if classroom_id else None
    if not selected_classroom:
        request.session.pop(TEACHER_SELECTED_CLASSROOM_SESSION_KEY, None)
        return redirect("screening_only:teacher_class_selection")

    q = (request.GET.get("q") or "").strip()
    lang = (request.GET.get("lang") or "en").strip().lower()

    students = (
        Student.objects.filter(organization=org, screenings__teacher=request.user)
        .distinct()
        .select_related("classroom")
    )

    # NEW: always filter by selected class/section
    students = students.filter(classroom_id=selected_classroom.id)

    if q:
        students = students.filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(student_code__icontains=q)
        )

    # Annotate last screening
    from django.db.models import OuterRef, Subquery

    last_screening = (
        Screening.objects.filter(student=OuterRef("pk"), teacher=request.user)
        .order_by("-screened_at")
    )
    students = students.annotate(
        last_screening_id=Subquery(last_screening.values("id")[:1]),
        last_screened_at=Subquery(last_screening.values("screened_at")[:1]),
        last_risk=Subquery(last_screening.values("risk_level")[:1]),
    ).order_by("last_name", "first_name", "id")

    for s in students:
        s.screening_url = reverse("screening_create", args=[s.id]) + f"?lang={lang}"

    # Existing add-student flow (creates new Student + Screening) is in screening app.
    # Keep passing classroom id so teacher_add_student can prefill class/section.
    add_student_url = reverse("teacher_add_student") + f"?classroom={selected_classroom.id}"

    return render(
        request,
        "screening_only/teacher_dashboard.html",
        {
            "org": org,
            "classrooms": classrooms,
            "selected_classroom_id": str(selected_classroom.id),
            "selected_classroom": selected_classroom,
            "q": q,
            "lang": lang,
            "students": students,
            "add_student_url": add_student_url,
            "cycle_start": cycle_start,
        },
    )


def parent_video(request: HttpRequest, token: str) -> HttpResponse:
    """
    Public parent education video page (language switch + link to result):contentReference[oaicite:20]{index=20}.
    """
    from messaging.i18n import edu_video_url

    screening_id = parse_parent_token(token)
    s = get_object_or_404(Screening.objects.select_related("student", "organization"), id=screening_id)

    lang = (request.GET.get("lang") or "en").strip().lower()
    # Provide 3 options: en, hi, local
    try:
        local_code = (s.organization.screening_only_profile.local_language_code or "").strip().lower() or "local"
    except Exception:
        local_code = "local"

    if lang not in ("en", "hi", "local", local_code):
        lang = "en"

    # We reuse existing env-configured URLs
    video = edu_video_url("local" if lang == local_code else lang)

    return render(
        request,
        "screening_only/parent_video.html",
        {
            "screening": s,
            "token": token,
            "lang": lang,
            "local_code": local_code,
            "video_url": video,
            "result_url": reverse("screening_only:parent_result", args=[token]),
        },
    )


def parent_result(request: HttpRequest, token: str) -> HttpResponse:
    """
    Public parent screening result view (linked from WhatsApp and from video page).
    """
    screening_id = parse_parent_token(token)
    s = get_object_or_404(
        Screening.objects.select_related("student", "student__classroom", "organization"),
        id=screening_id,
    )

    lang = (request.GET.get("lang") or "en").strip().lower()
    try:
        local_code = (s.organization.screening_only_profile.local_language_code or "").strip().lower() or "local"
    except Exception:
        local_code = "local"

    if lang not in ("en", "hi", "local", local_code):
        lang = "en"

    flags = s.red_flags or []
    flags_text = (
        (flags_to_text(flags, local_code) if lang == local_code else flags_to_text(flags, lang))
        or flags_to_text(flags, "en")
        or ""
    )

    # Reuse the common screening_result template for parents as well.
    # We pass is_parent_view so the template can hide teacher-only actions.
    return render(
        request,
        "screening/screening_result.html",
        {
            "s": s,
            "token": token,
            "lang": lang,
            "local_code": local_code,
            "flags_text": flags_text,
            "video_url": reverse("screening_only:parent_video", args=[token]),
            "is_parent_view": True,
        },
    )


def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.success(request, "Logged out.")
    return redirect("screening_only:enroll_school")


# ---------- Inditech ----------

from accounts.decorators import require_roles


@require_roles(Role.INDITECH)
def inditech_school_list(request: HttpRequest) -> HttpResponse:
    """
    Inditech – Registered Schools list:contentReference[oaicite:21]{index=21}.
    """
    schools = ScreeningSchoolProfile.objects.select_related("organization").order_by("-created_at")
    return render(
        request,
        "screening_only/inditech_school_list.html",
        {
            "schools": schools,
        },
    )


@require_roles(Role.INDITECH)
def inditech_school_dashboard(request: HttpRequest, org_id: int) -> HttpResponse:
    org = get_object_or_404(Organization, id=org_id)
    profile = getattr(org, "screening_only_profile", None)
    if not profile:
        return HttpResponseForbidden("Not a Screening Program school.")

    ay = request.GET.get("ay") or ""
    years = available_academic_years(org)
    if not ay:
        ay = years[0] if years else ""

    start_dt, end_dt = academic_year_range(ay)
    rows = screening_counts_by_class(org, start_dt, end_dt)

    return render(
        request,
        "screening_only/inditech_school_dashboard.html",
        {
            "org": org,
            "profile": profile,
            "ay": ay,
            "years": years,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "rows": rows,
        },
    )

def existing_admin_login(request: HttpRequest) -> HttpResponse:
    """
    Allows existing school admins to sign in from the enrollment page.
    After OAuth, we'll find their organization by matching their email.
    """
    # Store pending OAuth context in session (no org_id yet - we'll find it after OAuth)
    request.session["sp_oauth_role"] = "existing_admin"
    request.session.modified = True
    
    return redirect("screening_only:google_oauth_start")