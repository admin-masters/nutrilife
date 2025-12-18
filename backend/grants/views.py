from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.decorators import require_roles
from accounts.models import Role

from .forms import GrantForm, GrantorForm
from .models import Grant, Grantor


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, Role.SAPA_PGC, allow_superuser=True)
def grants_dashboard(request):
    grants = (
        Grant.objects.select_related("grantor")
        .all()
        .order_by("-created_at")
    )

    rows = []
    for g in grants:
        allocated = g.allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        available = (g.amount_received or Decimal("0")) - allocated
        rows.append({
            "g": g,
            "allocated": allocated,
            "available": available,
        })

    return render(request, "grants/dashboard.html", {"rows": rows})


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
def grantor_create(request):
    if request.method == "POST":
        form = GrantorForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Grantor created.")
            return redirect(reverse("grants:dashboard"))
    else:
        form = GrantorForm()
    return render(request, "grants/grantor_form.html", {"form": form})


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
def grant_create(request):
    if request.method == "POST":
        form = GrantForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Grant created.")
            return redirect(reverse("grants:dashboard"))
    else:
        form = GrantForm()
    return render(request, "grants/grant_form.html", {"form": form})


@require_roles(Role.SAPA_PGC, Role.SAPA_ADMIN, allow_superuser=True)
def grant_pgc_approve(request, grant_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    g = get_object_or_404(Grant, pk=grant_id)
    if g.status != Grant.Status.DRAFT:
        messages.info(request, "Grant is not in DRAFT.")
        return redirect(reverse("grants:dashboard"))
    g.status = Grant.Status.PGC_APPROVED
    g.save(update_fields=["status", "updated_at"])
    messages.success(request, "Grant marked as PGC approved.")
    return redirect(reverse("grants:dashboard"))


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
def grant_activate(request, grant_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    g = get_object_or_404(Grant, pk=grant_id)
    if g.status not in [Grant.Status.PGC_APPROVED, Grant.Status.DRAFT]:
        messages.info(request, "Grant cannot be activated from its current status.")
        return redirect(reverse("grants:dashboard"))
    g.status = Grant.Status.ACTIVE
    g.save(update_fields=["status", "updated_at"])
    messages.success(request, "Grant activated.")
    return redirect(reverse("grants:dashboard"))
