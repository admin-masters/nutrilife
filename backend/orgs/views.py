from django.contrib.auth import authenticate, login
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from accounts.models import Organization, User, OrgMembership, Role
from .forms import OrgSignupForm, OrgLoginForm


def _unique_screening_token(name: str) -> str:
    base = slugify(name) or "org"
    while True:
        token = f"{base}-{get_random_string(8)}"
        if not Organization.objects.filter(screening_link_token=token).exists():
            return token


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
                # If the user has exactly one org membership, set it into the session for continuity
                mems = user.memberships.filter(is_active=True).select_related("organization")
                if mems.count() == 1:
                    request.session["current_org_id"] = mems.first().organization_id
                # Redirect admins to dashboard; teachers will use their teacher link
                return redirect(reverse("assist:school_app_dashboard"))
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
        OrgMembership.objects.create(user=user, organization=org, role=Role.ORG_ADMIN)
        # Log in and set org context for continuity
        login(request, user)
        request.session["current_org_id"] = org.id
        return redirect(reverse("assist:school_app_dashboard"))

    return render(request, "orgs/start.html", {"mode": "signup", "signup_form": form, "login_form": OrgLoginForm()})
