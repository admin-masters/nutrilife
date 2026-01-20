from django import forms


class SchoolEnrollmentForm(forms.Form):
    school_name = forms.CharField(max_length=255)
    district = forms.CharField(max_length=128, required=False)
    address = forms.CharField(max_length=255, required=False)

    city = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=100, required=False)
    country = forms.CharField(max_length=64, required=False, initial="India")

    principal_name = forms.CharField(max_length=255, required=False)
    principal_email = forms.EmailField()

    operator_name = forms.CharField(max_length=255, required=False)
    operator_email = forms.EmailField(required=False)

    local_language_code = forms.CharField(
        max_length=12,
        required=False,
        help_text="Optional: ISO language code for local language (e.g., mr, te).",
    )

    def clean(self):
        cleaned = super().clean()
        pe = (cleaned.get("principal_email") or "").strip().lower()
        oe = (cleaned.get("operator_email") or "").strip().lower()

        if oe and oe == pe:
            # Allow same person to be both, but normalize by clearing operator if identical.
            cleaned["operator_email"] = ""
        return cleaned


class TeacherAccessForm(forms.Form):
    full_name = forms.CharField(max_length=255)
    email = forms.EmailField()
    accept_terms = forms.BooleanField(required=True)
