from django.contrib import admin
from .models import User, Organization, OrgMembership

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "is_staff", "is_active", "is_superuser", "date_joined")
    search_fields = ("email",)
    ordering = ("-date_joined",)
    filter_horizontal = ()
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

# @admin.register(Organization)
# class OrganizationAdmin(admin.ModelAdmin):
#     list_display = ("name", "org_type", "city", "state", "country", "is_active")
#     search_fields = ("name", "city", "state", "country")
#     list_filter = ("org_type", "is_active")

# @admin.register(OrgMembership)
# class OrgMembershipAdmin(admin.ModelAdmin):
#     list_display = ("user", "organization", "role", "is_active", "created_at","assistance_suspended")
#     list_filter = ("role", "is_active", "organization__org_type","assistance_suspended")
#     search_fields = ("user__email", "organization__name")

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "org_type", "city", "state", "country",
                    "is_active", "assistance_suspended")
    list_filter = ("org_type", "is_active", "assistance_suspended")
    search_fields = ("name", "city", "state", "country")

# --- Option 1: simplest (no org suspension on this list) ---
@admin.register(OrgMembership)
class OrgMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "organization__org_type")
    search_fields = ("user__email", "organization__name")