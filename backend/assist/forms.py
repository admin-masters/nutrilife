from django import forms

class ParentConsentForm(forms.Form):
    agree_consent = forms.BooleanField(label="I agree to receive monthly nutrition support for my child.", required=True)
    confirm_understanding = forms.BooleanField(label="I have read and understood the program information.", required=True)

    def as_form_data(self):
        d = self.cleaned_data.copy()
        # Store ONLY consent flags. We intentionally do not collect/stash
        # parent identifiers (name/phone/address) from the public link.
        return {
            "agree_consent": d.get("agree_consent", False),
            "confirm_understanding": d.get("confirm_understanding", False),
        }
