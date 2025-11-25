from datetime import date
from django.db import transaction
from django.utils import timezone
from audit.utils import audit_log
from .models import MonthlySupply
from django.db.models import Q, Count
from accounts.models import Organization
from .models import ScreeningMilestone, Enrollment

@transaction.atomic
def mark_supply_delivered(supply: MonthlySupply, delivered_on: date | None, actor=None):
    supply.set_delivered(delivered_on or timezone.now().date(), save=True)
    if actor:
        audit_log(actor, supply.enrollment.organization, "SUPPLY_DELIVERED",
                  target=supply, payload={"month_index": supply.month_index,
                                          "compliance_due_at": supply.compliance_due_at.isoformat()})
    return supply

def apply_gating_after_submission(supply: MonthlySupply):
    """
    If month m is COMPLIANT -> set month (m+1).ok_to_ship_next = True
    Else -> False. Month 6 has no next-supply.
    """
    comp = getattr(supply, "compliance", None)
    if not comp:
        return
    next_ms = MonthlySupply.objects.filter(enrollment=supply.enrollment, month_index=supply.month_index + 1).first()
    if not next_ms:
        return
    next_ms.ok_to_ship_next = (comp.status == comp.Status.COMPLIANT)
    next_ms.save(update_fields=["ok_to_ship_next", "updated_at"])

GRACE_DAYS = 0  # set >0 if you want a grace window after due date

@transaction.atomic
def compute_overdue_milestones(today: date | None = None) -> int:
    """
    Mark all DUE milestones whose due_on < today - GRACE_DAYS as OVERDUE.
    """
    today = today or timezone.now().date()
    threshold = today - timezone.timedelta(days=GRACE_DAYS)
    qs = ScreeningMilestone.objects.select_for_update().filter(
        status=ScreeningMilestone.Status.DUE,
        due_on__lt=threshold
    )
    n = qs.update(status=ScreeningMilestone.Status.OVERDUE)
    return n

@transaction.atomic
def evaluate_org_enforcement(org: Organization) -> None:
    """
    Suspend org if it has any OVERDUE milestones on ACTIVE enrollments.
    Unsuspend if none remain.
    """
    overdue_exists = ScreeningMilestone.objects.filter(
        enrollment__organization=org,
        enrollment__status=Enrollment.Status.ACTIVE,
        status=ScreeningMilestone.Status.OVERDUE
    ).exists()

    if overdue_exists and not org.assistance_suspended:
        org.assistance_suspended = True
        org.assistance_suspended_at = timezone.now()
        org.assistance_suspension_reason = "Overdue 3/6-month screening milestone(s)."
        org.save(update_fields=["assistance_suspended","assistance_suspended_at","assistance_suspension_reason"])
    elif not overdue_exists and org.assistance_suspended:
        org.assistance_suspended = False
        org.assistance_suspended_at = None
        org.assistance_suspension_reason = ""
        org.save(update_fields=["assistance_suspended","assistance_suspended_at","assistance_suspension_reason"])

def evaluate_enforcement_for_all_orgs():
    for org in Organization.objects.all().iterator():
        evaluate_org_enforcement(org)
