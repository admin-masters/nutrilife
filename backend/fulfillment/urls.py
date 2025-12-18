from django.urls import path

from . import views

app_name = "fulfillment"

urlpatterns = [
    path("fulfillment/", views.dashboard, name="dashboard"),
    path("fulfillment/production-orders/new", views.production_order_create, name="production_order_create"),

    path("fulfillment/manufacturer/production-orders", views.manufacturer_po_list, name="manufacturer_po_list"),
    path("fulfillment/manufacturer/production-orders/<int:po_id>/status", views.manufacturer_po_update_status, name="manufacturer_po_update_status"),

    path("fulfillment/shipments/new", views.shipment_create, name="shipment_create"),
    path("fulfillment/shipments/<int:shipment_id>", views.shipment_detail, name="shipment_detail"),

    path("fulfillment/logistics/shipments", views.logistics_shipments_list, name="logistics_shipments_list"),
    path("fulfillment/logistics/shipments/<int:shipment_id>/dispatch", views.shipment_dispatch, name="shipment_dispatch"),
    path("fulfillment/logistics/shipments/<int:shipment_id>/deliver", views.shipment_deliver, name="shipment_deliver"),

    path("fulfillment/school/shipments", views.school_incoming, name="school_incoming"),
    path("fulfillment/school/shipments/<int:shipment_id>/confirm", views.school_confirm_delivery, name="school_confirm_delivery"),
]
