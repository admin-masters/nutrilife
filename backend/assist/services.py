from typing import Iterable, List, Tuple
from django.db import transaction
from django.db.models.functions import Lower, Coalesce
from django.db.models import Value, CharField
from django.utils import timezone
from accounts.models import Organization, User
from roster.models import Student
from .models import Application, ApprovalBatch, BatchItem
from program.models import Enrollment
from audit.utils import audit_log
from django.conf import settings
from decimal import Decimal

try:
    from grants.models import Grant, GrantAllocation
except Exception:  # pragma: no cover
    Grant = None  # type: ignore
    GrantAllocation = None  # type: ignore


def _grant_cost_per_enrollment():
    """Configurable per-enrollment allocation amount.

    Default is 0 (no funding bookkeeping) so Phase 1 installs keep working.
    """
    try:
        raw = getattr(settings, "NUTRILIFT_GRANT_COST_PER_ENROLLMENT", 0) or 0
        return Decimal(str(raw))
    except Exception:
        return Decimal("0")

def _alphabetic_qs(org: Organization):
    # Case-insensitive ordering; blank last_name handled as ''
    return (Application.objects
            .select_related("student")
            .filter(organization=org, status=Application.Status.FORWARDED)
            .order_by(Coalesce(Lower("student__last_name"), Value("", output_field=CharField())),
                      Coalesce(Lower("student__first_name"), Value("", output_field=CharField()))))

@transaction.atomic
def approve_all(org: Organization, actor: User | None, grant_id: int | None = None) -> Tuple[ApprovalBatch, int]:
    pending = list(_alphabetic_qs(org))
    grant = None
    if grant_id and Grant:
        grant = Grant.objects.select_for_update().get(pk=int(grant_id))
    batch = ApprovalBatch.objects.create(
        organization=org,
        created_by=actor,
        method=ApprovalBatch.Method.ALL_PENDING,
        n_selected=len(pending),
        grant=grant,
    )
    approved_count = 0
    cost = _grant_cost_per_enrollment()
    remaining: Decimal | None = None
    if grant and cost > 0:
        # Precompute remaining at the start of the transaction (and decrement locally per approval)
        remaining = Decimal(str(grant.available_amount()))
    for app in pending:
        if app.status != Application.Status.FORWARDED:
            BatchItem.objects.create(approval_batch=batch, application=app, outcome=BatchItem.Outcome.SKIPPED, note="Not forwarded")
            continue

        if grant and cost > 0 and remaining is not None and remaining < cost:
            BatchItem.objects.create(
                approval_batch=batch,
                application=app,
                outcome=BatchItem.Outcome.SKIPPED,
                note="Insufficient grant funds",
            )
            continue
        # Transition
        app.status = Application.Status.APPROVED
        app.sapa_reviewed_at = timezone.now()
        app.save(update_fields=["status","sapa_reviewed_at","updated_at"])
        BatchItem.objects.create(approval_batch=batch, application=app, outcome=BatchItem.Outcome.APPROVED)
        # Ensure Enrollment
        enrollment = getattr(app, "enrollment", None)
        if not enrollment:
            enrollment = Enrollment.create_for_approved(app, actor)

        if grant and cost > 0 and GrantAllocation and enrollment:
            GrantAllocation.objects.get_or_create(
                grant=grant,
                enrollment=enrollment,
                defaults={"amount": cost, "allocated_by": actor},
            )
            if remaining is not None:
                remaining -= cost
        approved_count += 1

    audit_log(actor, org, "SAPA_APPROVAL_BATCH", target=batch, payload={"method":"ALL_PENDING","approved":approved_count})
    return batch, approved_count

@transaction.atomic
def approve_top_n(org: Organization, n: int, actor: User | None, grant_id: int | None = None) -> Tuple[ApprovalBatch, int, int]:
    all_pending = list(_alphabetic_qs(org))
    to_approve = all_pending[:max(0, int(n))]
    grant = None
    if grant_id and Grant:
        grant = Grant.objects.select_for_update().get(pk=int(grant_id))
    batch = ApprovalBatch.objects.create(
        organization=org,
        created_by=actor,
        method=ApprovalBatch.Method.TOP_N_ALPHA,
        n_selected=len(to_approve),
        grant=grant,
    )
    approved_count = 0
    skipped = 0
    cost = _grant_cost_per_enrollment()
    remaining: Decimal | None = None
    if grant and cost > 0:
        remaining = Decimal(str(grant.available_amount()))
    for i, app in enumerate(all_pending):
        if app in to_approve and app.status == Application.Status.FORWARDED:
            if grant and cost > 0 and remaining is not None and remaining < cost:
                BatchItem.objects.create(
                    approval_batch=batch,
                    application=app,
                    outcome=BatchItem.Outcome.SKIPPED,
                    note="Insufficient grant funds",
                )
                skipped += 1
                continue
            app.status = Application.Status.APPROVED
            app.sapa_reviewed_at = timezone.now()
            app.save(update_fields=["status","sapa_reviewed_at","updated_at"])
            BatchItem.objects.create(approval_batch=batch, application=app, outcome=BatchItem.Outcome.APPROVED)
            enrollment = getattr(app, "enrollment", None)
            if not enrollment:
                enrollment = Enrollment.create_for_approved(app, actor)

            if grant and cost > 0 and GrantAllocation and enrollment:
                GrantAllocation.objects.get_or_create(
                    grant=grant,
                    enrollment=enrollment,
                    defaults={"amount": cost, "allocated_by": actor},
                )
                if remaining is not None:
                    remaining -= cost
            approved_count += 1
        else:
            BatchItem.objects.create(approval_batch=batch, application=app, outcome=BatchItem.Outcome.SKIPPED, note="Not in Top-N or not forwarded")
            skipped += 1
    audit_log(actor, org, "SAPA_APPROVAL_BATCH", target=batch, payload={"method":"TOP_N_ALPHA","approved":approved_count,"skipped":skipped})
    return batch, approved_count, skipped

@transaction.atomic
def reject_all(org: Organization, actor: User | None) -> Tuple[ApprovalBatch, int]:
    pending = list(_alphabetic_qs(org))
    batch = ApprovalBatch.objects.create(organization=org, created_by=actor, method=ApprovalBatch.Method.ALL_PENDING, n_selected=0)
    rejected_count = 0
    for app in pending:
        app.status = Application.Status.REJECTED
        app.sapa_reviewed_at = timezone.now()
        app.save(update_fields=["status","sapa_reviewed_at","updated_at"])
        BatchItem.objects.create(approval_batch=batch, application=app, outcome=BatchItem.Outcome.REJECTED)
        rejected_count += 1
    audit_log(actor, org, "SAPA_REJECTION_BATCH", target=batch, payload={"rejected":rejected_count})
    return batch, rejected_count
