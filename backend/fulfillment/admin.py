from django.contrib import admin

from .models import ProductionOrder, SchoolShipment, ShipmentItem


@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "month", "manufacturer", "total_packs", "status", "created_at")
    list_filter = ("status", "month")
    search_fields = ("id", "manufacturer__name")


class ShipmentItemInline(admin.TabularInline):
    model = ShipmentItem
    extra = 0
    autocomplete_fields = ("monthly_supply",)


@admin.register(SchoolShipment)
class SchoolShipmentAdmin(admin.ModelAdmin):
    list_display = ("id", "school", "month_index", "status", "logistics_partner", "tracking_number", "created_at")
    list_filter = ("status", "month_index")
    search_fields = ("school__name", "tracking_number")
    inlines = [ShipmentItemInline]


@admin.register(ShipmentItem)
class ShipmentItemAdmin(admin.ModelAdmin):
    list_display = ("id", "shipment", "monthly_supply", "pack_qty")
    search_fields = ("shipment__id", "monthly_supply__id")
