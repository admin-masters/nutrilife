from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import require_roles
from accounts.models import Organization, Role
from audit.utils import audit_log
from program.models import MonthlySupply, Enrollment
from program.services import mark_supply_delivered

from .forms import ProductionOrderForm, ShipmentCreateForm
from .models import ProductionOrder, SchoolShipment, ShipmentItem


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
def dashboard(request):
    pos = ProductionOrder.objects.select_related("manufacturer").order_by("-created_at")[:200]
    shipments = SchoolShipment.objects.select_related("school", "logistics_partner").order_by("-created_at")[:200]
    return render(request, "fulfillment/dashboard.html", {"pos": pos, "shipments": shipments})


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
def production_order_create(request):
    if request.method == "POST":
        form = ProductionOrderForm(request.POST)
        if form.is_valid():
            po = form.save(commit=False)
            po.created_by = request.user
            po.save()
            audit_log(request.user, None, "PRODUCTION_ORDER_CREATED", target=po)
            messages.success(request, "Production order created.")
            return redirect(reverse("fulfillment:dashboard"))
    else:
        form = ProductionOrderForm()
    return render(request, "fulfillment/po_form.html", {"form": form})


@require_roles(Role.MANUFACTURER, allow_superuser=True)
def manufacturer_po_list(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    pos = ProductionOrder.objects.filter(manufacturer=org).order_by("-created_at")
    return render(
        request,
        "fulfillment/manufacturer_po_list.html",
        {"pos": pos, "org": org, "status_choices": ProductionOrder.Status.choices},
    )


@require_roles(Role.MANUFACTURER, allow_superuser=True)
def manufacturer_po_update_status(request, po_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    po = get_object_or_404(ProductionOrder, pk=po_id, manufacturer=org)
    new_status = request.POST.get("status")
    if new_status not in [c[0] for c in ProductionOrder.Status.choices]:
        return HttpResponseBadRequest("Invalid status")
    po.status = new_status
    po.save(update_fields=["status", "updated_at"])
    audit_log(request.user, org, "PRODUCTION_ORDER_STATUS_UPDATED", target=po, payload={"status": new_status})
    return redirect(reverse("fulfillment:manufacturer_po_list"))


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, allow_superuser=True)
def shipment_create(request):
    """Create a school shipment by auto-attaching eligible MonthlySupply rows."""
    if request.method == "POST":
        form = ShipmentCreateForm(request.POST)
        if form.is_valid():
            shipment = form.save(commit=False)
            shipment.created_by = request.user
            # Do not allow shipments for suspended schools
            if shipment.school.assistance_suspended:
                return HttpResponseForbidden(
                    "School is suspended due to overdue screening milestones; cannot create shipments."
                )
            shipment.save()

            # Attach eligible supplies
            supplies = MonthlySupply.objects.filter(
                enrollment__organization=shipment.school,
                enrollment__status=Enrollment.Status.ACTIVE,
                month_index=shipment.month_index,
                delivered_on__isnull=True,
            )
            if shipment.month_index > 1:
                supplies = supplies.filter(ok_to_ship_next=True)

            items = [ShipmentItem(shipment=shipment, monthly_supply=ms, pack_qty=1) for ms in supplies]
            if items:
                ShipmentItem.objects.bulk_create(items, ignore_conflicts=True)

            audit_log(request.user, shipment.school, "SHIPMENT_CREATED", target=shipment, payload={"items": len(items)})
            messages.success(request, f"Shipment created with {len(items)} item(s).")
            return redirect(reverse("fulfillment:shipment_detail", args=[shipment.id]))
    else:
        form = ShipmentCreateForm()
    return render(request, "fulfillment/shipment_form.html", {"form": form})


@require_roles(Role.SAPA_ADMIN, Role.INDITECH, Role.LOGISTICS, Role.ORG_ADMIN, allow_superuser=True)
def shipment_detail(request, shipment_id: int):
    shipment = get_object_or_404(SchoolShipment.objects.select_related("school", "logistics_partner"), pk=shipment_id)

    # Basic authorization: logistics sees theirs, school sees theirs, admins see all
    if request.user.is_superuser:
        pass
    else:
        role = getattr(getattr(request, "membership", None), "role", None)
        if role == Role.LOGISTICS and request.org and shipment.logistics_partner_id != request.org.id:
            return HttpResponseForbidden("Not allowed")
        if role == Role.ORG_ADMIN and request.org and shipment.school_id != request.org.id:
            return HttpResponseForbidden("Not allowed")

    items = shipment.items.select_related("monthly_supply__enrollment__student").order_by("monthly_supply__enrollment__student__last_name")
    return render(request, "fulfillment/shipment_detail.html", {"shipment": shipment, "items": items})


@require_roles(Role.LOGISTICS, allow_superuser=True)
def logistics_shipments_list(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    shipments = SchoolShipment.objects.filter(logistics_partner=org).select_related("school").order_by("-created_at")
    return render(request, "fulfillment/logistics_shipments_list.html", {"shipments": shipments, "org": org})


@require_roles(Role.LOGISTICS, allow_superuser=True)
def shipment_dispatch(request, shipment_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    shipment = get_object_or_404(SchoolShipment, pk=shipment_id, logistics_partner=org)
    shipment.status = SchoolShipment.Status.DISPATCHED
    shipment.dispatched_at = timezone.now()
    shipment.tracking_number = (request.POST.get("tracking_number") or shipment.tracking_number)
    shipment.save(update_fields=["status", "dispatched_at", "tracking_number", "updated_at"])
    audit_log(request.user, shipment.school, "SHIPMENT_DISPATCHED", target=shipment, payload={"tracking": shipment.tracking_number})
    return redirect(reverse("fulfillment:logistics_shipments_list"))


def _mark_shipment_delivered(shipment: SchoolShipment, actor):
    if shipment.status == SchoolShipment.Status.DELIVERED:
        return
    shipment.status = SchoolShipment.Status.DELIVERED
    shipment.delivered_at = timezone.now()
    shipment.save(update_fields=["status", "delivered_at", "updated_at"])

    for item in shipment.items.select_related("monthly_supply"):
        mark_supply_delivered(item.monthly_supply, delivered_on=shipment.delivered_at.date(), actor=actor)


@require_roles(Role.LOGISTICS, allow_superuser=True)
def shipment_deliver(request, shipment_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    shipment = get_object_or_404(SchoolShipment, pk=shipment_id, logistics_partner=org)
    _mark_shipment_delivered(shipment, actor=request.user)
    audit_log(request.user, shipment.school, "SHIPMENT_DELIVERED", target=shipment)
    return redirect(reverse("fulfillment:logistics_shipments_list"))


@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def school_incoming(request):
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    shipments = SchoolShipment.objects.filter(school=org).order_by("-created_at")[:200]
    return render(request, "fulfillment/school_incoming.html", {"shipments": shipments, "org": org})


@require_roles(Role.ORG_ADMIN, allow_superuser=True)
def school_confirm_delivery(request, shipment_id: int):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    org = request.org
    if not org:
        return HttpResponseForbidden("Organization context required.")
    shipment = get_object_or_404(SchoolShipment, pk=shipment_id, school=org)
    _mark_shipment_delivered(shipment, actor=request.user)
    audit_log(request.user, org, "SHIPMENT_CONFIRMED_BY_SCHOOL", target=shipment)
    return redirect(reverse("fulfillment:school_incoming"))
