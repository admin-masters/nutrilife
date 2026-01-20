from django.contrib.auth import authenticate, login
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from accounts.models import Organization, User, OrgMembership, Role
from .forms import OrgSignupForm, OrgLoginForm
from django.http import HttpResponse
from accounts.decorators import require_roles


def _unique_screening_token(name: str) -> str:
    base = slugify(name) or "org"
    while True:
        token = f"{base}-{get_random_string(8)}"
        if not Organization.objects.filter(screening_link_token=token).exists():
            return token

# --- NEW: OrgType -> Role mapping for the org creator/admin user ---
ORG_TYPE_TO_ROLE = {
    Organization.OrgType.SCHOOL: Role.ORG_ADMIN,        # "School Admin"
    Organization.OrgType.NGO: Role.ORG_ADMIN,           # "School Admin"
    Organization.OrgType.SAPA: Role.SAPA_ADMIN,         # "SAPA Admin"
    Organization.OrgType.INDITECH: Role.INDITECH,       # "Inditech"
    Organization.OrgType.MANUFACTURER: Role.MANUFACTURER,  # "Manufacturer"
    Organization.OrgType.LOGISTICS: Role.LOGISTICS,     # "Logistics Partner"
}

def _pick_primary_membership(user: User):
    """
    Pick the membership we’ll treat as the user's primary org context.
    Current product assumption: 1 user -> 1 org (common case).
    """
    return (
        user.memberships
            .filter(is_active=True)
            .select_related("organization")
            .order_by("created_at")
            .first()
    )

def _redirect_for_membership(mem: OrgMembership):
    """
    Redirect to the most significant dashboard page based on membership role.
    Keep this mapping EXACTLY as requested.
    """
    role = mem.role

    if role == Role.ORG_ADMIN:
        try:
            mem.organization.screening_only_profile
            return redirect(reverse("screening_only:admin_link_dashboard"))
        except Exception:
            return redirect(reverse("assist:school_app_dashboard"))

    if role == Role.SAPA_ADMIN:
        return redirect(reverse("assist:sapa_approvals_dashboard"))  # /assist/sapa/approvals

    if role == Role.INDITECH:
        return redirect(reverse("reporting:inditech_dashboard"))  # /reporting/inditech


    if role == Role.MANUFACTURER:
        return redirect(reverse("fulfillment:manufacturer_po_list"))  # /fulfillment/manufacturer/production-orders

    if role == Role.LOGISTICS:
        return redirect(reverse("fulfillment:logistics_shipments_list"))  # /fulfillment/logistics/shipments

    # Optional safety fallback:
    if role == Role.TEACHER:
        return redirect(reverse("teacher_portal_token", args=[mem.organization.screening_link_token]))

    return redirect(reverse("orgs:org_start"))


@transaction.atomic
def org_start(request):
    """One page with two modes: signup (create org) and login (existing org)."""
    mode = request.GET.get("mode", "signup")
    if request.method == "POST":
        mode = request.POST.get("mode", mode)

    if mode == "login":
        form = OrgLoginForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            user = authenticate(request, email=form.cleaned_data["email"], password=form.cleaned_data["password"])
            if user is None:
                form.add_error(None, "Invalid email or password.")
            else:
                login(request, user)

                mem = _pick_primary_membership(user)
                if not mem:
                    form.add_error(None, "No active organization membership found for this user.")
                else:
                # ensure org context is set for middleware-protected dashboards
                    request.session["current_org_id"] = mem.organization_id
                    return _redirect_for_membership(mem)

        return render(request, "orgs/start.html", {"mode": "login", "login_form": form, "signup_form": OrgSignupForm()})

    # Default: signup
    form = OrgSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # Create organization
        org = Organization.objects.create(
            name=form.cleaned_data["name"],
            org_type=form.cleaned_data["org_type"],
            city=form.cleaned_data["city"],
            state=form.cleaned_data["state"],
            country=form.cleaned_data["country"],
            # timezone default = "Asia/Kolkata" (model default)
            screening_link_token=_unique_screening_token(form.cleaned_data["name"]),
            # is_active default True (model default)
        )
        # Create admin user
        user = User.objects.create_user(
            email=form.cleaned_data["admin_email"],
            password=form.cleaned_data["password1"],
            is_staff=True  # optional; keeps access to Django admin if you wish
        )
        # Link membership
        selected_org_type = org.org_type  # stored on Organization
        mapped_role = ORG_TYPE_TO_ROLE.get(selected_org_type, Role.ORG_ADMIN)

        mem = OrgMembership.objects.create(user=user, organization=org, role=mapped_role)

        # Log in and set org context for continuity
        login(request, user)
        request.session["current_org_id"] = org.id
        return _redirect_for_membership(mem)


    return render(request, "orgs/start.html", {"mode": "signup", "signup_form": form, "login_form": OrgLoginForm()})


