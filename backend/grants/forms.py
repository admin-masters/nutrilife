from decimal import Decimal

from django import forms

from .models import Grant, Grantor


class GrantorForm(forms.ModelForm):
    class Meta:
        model = Grantor
        fields = ["name", "contact_email", "contact_phone_e164", "organization"]


class GrantForm(forms.ModelForm):
    class Meta:
        model = Grant
        fields = [
            "grantor",
            "title",
            "currency",
            "amount_committed",
            "amount_received",
            "status",
            "start_date",
            "end_date",
            "notes",
        ]

    def clean_amount_committed(self):
        v = self.cleaned_data.get("amount_committed")
        if v is None:
            return Decimal("0")
        if v < 0:
            raise forms.ValidationError("Amount committed cannot be negative.")
        return v

    def clean_amount_received(self):
        v = self.cleaned_data.get("amount_received")
        if v is None:
            return Decimal("0")
        if v < 0:
            raise forms.ValidationError("Amount received cannot be negative.")
        return v
