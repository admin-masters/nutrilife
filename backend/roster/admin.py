from django.contrib import admin
from .models import Classroom, Guardian, Student, StudentGuardian

@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("organization", "grade", "division", "created_at")
    list_filter = ("organization", "grade")
    search_fields = ("organization__name", "grade", "division")

@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("organization", "full_name", "phone_e164", "whatsapp_opt_in")
    list_filter = ("organization", "whatsapp_opt_in")
    search_fields = ("full_name", "phone_e164")

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("organization", "full_name", "gender", "classroom", "is_low_income")
    list_filter = ("organization", "gender", "classroom", "is_low_income")
    search_fields = ("first_name", "last_name", "student_code", "primary_guardian__phone_e164")

@admin.register(StudentGuardian)
class StudentGuardianAdmin(admin.ModelAdmin):
    list_display = ("student", "guardian", "relationship", "created_at")
    search_fields = ("student__first_name", "guardian__full_name")
