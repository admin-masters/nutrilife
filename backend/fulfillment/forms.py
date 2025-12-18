from django import forms

from accounts.models import Organization

from .models import ProductionOrder, SchoolShipment


class ProductionOrderForm(forms.ModelForm):
    class Meta:
        model = ProductionOrder
        fields = ["manufacturer", "month", "total_packs", "notes"]


class ShipmentCreateForm(forms.ModelForm):
    class Meta:
        model = SchoolShipment
        fields = ["school", "logistics_partner", "month_index", "tracking_number"]

    def clean_month_index(self):
        v = int(self.cleaned_data.get("month_index") or 0)
        if v < 1 or v > 6:
            raise forms.ValidationError("Month index must be between 1 and 6")
        return v
