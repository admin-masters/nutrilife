from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseBadRequest
from django.urls import reverse
from django.db.models import Count
from accounts.decorators import require_roles
from accounts.models import Role, Organization
from .models import Application
from .services import approve_all, approve_top_n, reject_all
from django.db import models
from django.db.models import Count, Q

@require_roles(Role.SAPA_ADMIN, allow_superuser=True)
def sapa_approvals_dashboard(request):
    # Schools with counts of forwarded & approved applications
    schools = (
        Organization.objects
        .annotate(
            forwarded_count=Count(
                "applications",
                filter=Q(applications__status=Application.Status.FORWARDED),
            ),
            approved_count=Count(
                "applications",
                filter=Q(applications__status=Application.Status.APPROVED),
            ),
        )
        # If you only want schools that currently have pending-for-SAPA items:
        # .filter(forwarded_count__gt=0)
        .order_by("name")
    )

    school_id = request.GET.get("school")
    selected_school = None
    pending = []
    approved = 0

    if school_id:
        selected_school = get_object_or_404(Organization, pk=int(school_id))
        pending = (
            Application.objects
            .select_related("student", "guardian")
            .filter(organization=selected_school, status=Application.Status.FORWARDED)
            .order_by("student__last_name", "student__first_name")
        )
        approved = (
            Application.objects
            .filter(organization=selected_school, status=Application.Status.APPROVED)
            .count()
        )

    return render(
        request,
        "assist/sapa_approvals.html",
        {
            "schools": schools,
            "selected_school": selected_school,
            "pending": pending,
            "approved_count": approved,
        },
    )


@require_roles(Role.SAPA_ADMIN, allow_superuser=True)
def sapa_approve_all(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    school_id = request.POST.get("school_id")
    org = get_object_or_404(Organization, pk=int(school_id))
    _, count = approve_all(org, request.user)
    return redirect(reverse("assist:sapa_approvals_dashboard") + f"?school={org.id}&ok=approved_all&n={count}")

@require_roles(Role.SAPA_ADMIN, allow_superuser=True)
def sapa_approve_top_n(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    school_id = request.POST.get("school_id")
    n = int(request.POST.get("n","0"))
    org = get_object_or_404(Organization, pk=int(school_id))
    _, approved, skipped = approve_top_n(org, n, request.user)
    return redirect(reverse("assist:sapa_approvals_dashboard") + f"?school={org.id}&ok=approved_top_n&n={approved}&skipped={skipped}")

@require_roles(Role.SAPA_ADMIN, allow_superuser=True)
def sapa_reject_all(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    school_id = request.POST.get("school_id")
    org = get_object_or_404(Organization, pk=int(school_id))
    _, count = reject_all(org, request.user)
    return redirect(reverse("assist:sapa_approvals_dashboard") + f"?school={org.id}&ok=rejected_all&n={count}")
