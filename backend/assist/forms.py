from django import forms

class ParentConsentForm(forms.Form):
    parent_full_name = forms.CharField(label="Your Full Name", max_length=255, required=False)
    parent_phone_e164 = forms.CharField(label="Your WhatsApp Number (+countrycode...)", max_length=20, required=False)

    agree_consent = forms.BooleanField(label="I agree to receive monthly nutrition support for my child.", required=True)
    confirm_understanding = forms.BooleanField(label="I have read and understood the program information.", required=True)

    address_line1 = forms.CharField(label="Address line 1", required=False)
    address_line2 = forms.CharField(label="Address line 2", required=False)
    city = forms.CharField(required=False)
    state = forms.CharField(required=False)
    postal_code = forms.CharField(required=False)

    def as_form_data(self):
        d = self.cleaned_data.copy()
        # Remove checkboxes that are captured by fields above:
        return {
            "parent_full_name": d.get("parent_full_name"),
            "parent_phone_e164": d.get("parent_phone_e164"),
            "address": {
                "line1": d.get("address_line1", ""),
                "line2": d.get("address_line2", ""),
                "city": d.get("city", ""),
                "state": d.get("state", ""),
                "postal_code": d.get("postal_code", ""),
            },
            "agree_consent": d.get("agree_consent", False),
            "confirm_understanding": d.get("confirm_understanding", False),
        }
