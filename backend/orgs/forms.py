from django import forms
from accounts.models import Organization

class OrgSignupForm(forms.Form):
    # Organization fields
    name = forms.CharField(max_length=255, label="Organization name")
    org_type = forms.ChoiceField(choices=Organization.OrgType.choices, label="Organization type")
    city = forms.CharField(max_length=128, required=False)
    state = forms.CharField(max_length=128, required=False)
    country = forms.CharField(max_length=64, required=False)
    # Admin user fields
    admin_email = forms.EmailField(label="Admin email")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        return data


class OrgLoginForm(forms.Form):
    email = forms.EmailField(label="Email")
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
