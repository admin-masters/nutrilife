from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponseBadRequest
from django.urls import reverse
from django.utils import timezone
from django.http import HttpResponseForbidden
from audit.utils import audit_log
from .models import MonthlySupply
from .models import MonthlySupply, ComplianceSubmission
from .forms import ComplianceForm
from .services import mark_supply_delivered,apply_gating_after_submission
from accounts.decorators import require_roles
from accounts.models import Role
from django.db.models import Count, Q
from .models import ScreeningMilestone, Enrollment

def qr_landing(request, token: str):
    """
    Public landing after scanning a pack QR.
    Shows instructions + link to start the compliance form (Sprint 6).
    """
    supply = get_object_or_404(MonthlySupply, qr_token=token)
    org = supply.enrollment.organization
    student = supply.enrollment.student

    audit_log(user=None, org=org, action="QR_OPENED", target=supply, payload={"month": supply.month_index})

    return render(request, "program/qr_landing.html", {
        "supply": supply,
        "student": student,
        "org": org,
        "is_delivered": bool(supply.delivered_on),
    })


# def compliance_start(request):
#     """
#     Placeholder page that will link into Sprint 6 compliance form.
#     Accepts ?token=<qr_token>
#     """
#     token = request.GET.get("token") or ""
#     if not token:
#         return HttpResponseBadRequest("Missing token")
#     supply = get_object_or_404(MonthlySupply, qr_token=token)
#     return render(request, "program/compliance_start.html", {
#         "supply": supply,
#         "due": supply.compliance_due_at,
#         "delivered_on": supply.delivered_on,
#     })


# Optional helper for lightweight fulfillment outside admin (RBAC kept simple here).
from accounts.decorators import require_roles
from accounts.models import Role

# @require_roles(Role.ORG_ADMIN, Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
# def mark_delivered_view(request, supply_id: int):
#     from .services import mark_supply_delivered
#     if request.method != "POST":
#         return HttpResponseBadRequest("POST required")
#     supply = get_object_or_404(MonthlySupply, pk=supply_id)
#     mark_supply_delivered(supply, delivered_on=None, actor=request.user)
#     # redirect to admin change page or a list you already have
#     return redirect(f"/admin/program/monthlysupply/{supply.id}/change/")

def compliance_form(request, token: str):
    ms = get_object_or_404(MonthlySupply, qr_token=token)
    comp, _ = ComplianceSubmission.objects.get_or_create(monthly_supply=ms)

    if request.method == "POST":
        form = ComplianceForm(request.POST)
        if form.is_valid():
            comp.status = form.cleaned_data["status"]
            comp.submitted_at = timezone.now()
            comp.responses = {"notes": form.cleaned_data.get("notes","")}
            comp.save(update_fields=["status","submitted_at","responses","updated_at"])

            apply_gating_after_submission(ms)
            audit_log(user=None, org=ms.enrollment.organization, action="COMPLIANCE_SUBMITTED",
                      target=comp, payload={"status": comp.status, "supply_id": ms.id})

            return redirect(reverse("program:compliance_success", args=[ms.qr_token]))
    else:
        form = ComplianceForm(initial={"status": "COMPLIANT"})

    return render(request, "program/compliance_form.html", {
        "supply": ms, "form": form,
        "due": ms.compliance_due_at, "delivered_on": ms.delivered_on
    })

def compliance_success(request, token: str):
    ms = get_object_or_404(MonthlySupply, qr_token=token)
    comp = getattr(ms, "compliance", None)
    return render(request, "program/compliance_success.html", {"supply": ms, "comp": comp})

def compliance_start(request):
    """
    Backward-compatibility for Sprint 5 URL:
    /program/compliance/start?token=<qr_token>
    """
    token = request.GET.get("token")
    if not token:
        return HttpResponseBadRequest("Missing token")
    return redirect(reverse("program:compliance_form", args=[token]))

@require_roles(Role.ORG_ADMIN, Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
def mark_delivered_view(request, supply_id: int):
    """
    Legacy-compatible wrapper so older URLs that point to 'mark_delivered_view'
    continue to work. Internally we call the new helper mark_supply_delivered().
    """
    
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    
    #commented for pytest fixing in phase 11

    # org = ms.enrollment.organization
    # if org.assistance_suspended:
    #     return HttpResponseForbidden("School is suspended due to overdue screening milestones; please complete the required 3/6‑month screenings.")
    
    # ms = get_object_or_404(MonthlySupply, pk=supply_id)
    #added for the pytest fixing
    ms = get_object_or_404(MonthlySupply, pk=supply_id)
    org = ms.enrollment.organization
    if org.assistance_suspended:
        return HttpResponseForbidden(
            "School is suspended due to overdue screening milestones; "
            "please complete the required 3/6‑month screenings."
        )
        
    mark_supply_delivered(ms, delivered_on=None, actor=request.user)
    return redirect(f"/admin/program/monthlysupply/{ms.id}/change/")

@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def milestones_dashboard(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")

    today = timezone.now().date()
    upcoming_threshold = today + timezone.timedelta(days=14)

    milestones = (ScreeningMilestone.objects
                  .select_related("enrollment__student")
                  .filter(enrollment__organization=org)
                  .order_by("due_on"))

    counts = {
        "due": milestones.filter(status=ScreeningMilestone.Status.DUE, due_on__lte=upcoming_threshold).count(),
        "overdue": milestones.filter(status=ScreeningMilestone.Status.OVERDUE).count(),
        "completed": milestones.filter(status=ScreeningMilestone.Status.COMPLETED).count(),
    }

    due_list = milestones.filter(status=ScreeningMilestone.Status.DUE, due_on__lte=upcoming_threshold)
    overdue_list = milestones.filter(status=ScreeningMilestone.Status.OVERDUE)

    return render(request, "program/milestones_school.html", {
        "org": org,
        "counts": counts,
        "due_list": due_list,
        "overdue_list": overdue_list,
        "today": today,
        "suspended": org.assistance_suspended,
        "reason": org.assistance_suspension_reason,
    })

@require_roles(Role.SAPA_ADMIN, allow_superuser=True)
def milestones_sapa_overview(request):
    # Simple aggregate: overdue counts per org
    rows = (ScreeningMilestone.objects
            .filter(enrollment__status=Enrollment.Status.ACTIVE)
            .values("enrollment__organization__id","enrollment__organization__name")
            .annotate(
                overdue=Count("id", filter=Q(status=ScreeningMilestone.Status.OVERDUE)),
                due=Count("id", filter=Q(status=ScreeningMilestone.Status.DUE)),
                completed=Count("id", filter=Q(status=ScreeningMilestone.Status.COMPLETED)),
            )
            .order_by("enrollment__organization__name"))

    return render(request, "program/milestones_sapa.html", {"rows": rows})
