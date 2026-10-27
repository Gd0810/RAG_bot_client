from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.utils.text import slugify

from .models import OrganizationProfile, KnowledgeDocument, Department, VisitorRequest
from .services import ingestion


@admin.register(OrganizationProfile)
class OrganizationProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "tagline", "theme_color", "dashboard_mode")

    fieldsets = (
        ("Basic Info & Modes", {"fields": ("name", "tagline", "about", "dashboard_mode")}),
        ("About Highlights", {
            "fields": (
                "about_point_1",
                "about_point_2",
                "about_point_3",
                "about_image_1",
                "about_image_2",
            ),
        }),
        ("Images (placeholders are used automatically if left blank)", {
            "fields": ("hero_image", "gallery_image_1", "gallery_image_2"),
        }),
        ("Contact & Links", {
            "fields": (
                "contact_email",
                "website_url",
                "about_url",
                "contact_url",
                "theme_color",
            ),
        }),
    )

    def has_add_permission(self, request):
        # Singleton: block adding a second profile once one exists.
        return not OrganizationProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class DepartmentForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        help_text="Set or update password for department dashboard login.",
    )

    class Meta:
        model = Department
        fields = ["department_name", "department_email", "password", "is_active"]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    form = DepartmentForm
    list_display = ("department_name", "department_email", "user", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("department_name", "department_email")

    def save_model(self, request, obj, form, change):
        raw_password = form.cleaned_data.get("password")
        dept_name = form.cleaned_data.get("department_name", "")
        dept_email = form.cleaned_data.get("department_email", "")

        # Generate unique username for the department admin
        username = slugify(dept_name).replace("-", "_")
        if not username:
            username = "dept_admin"
        
        # Link or create Django User
        user = obj.user
        if not user:
            user, created = User.objects.get_or_create(username=username, defaults={"email": dept_email})
            if not created and user.department_profile and user.department_profile != obj:
                username = f"{username}_{Department.objects.count() + 1}"
                user = User.objects.create(username=username, email=dept_email)
        
        user.username = username
        user.email = dept_email
        user.is_staff = True  # Allows login access
        if raw_password:
            user.set_password(raw_password)
        user.save()

        obj.user = user
        super().save_model(request, obj, form, change)


@admin.register(VisitorRequest)
class VisitorRequestAdmin(admin.ModelAdmin):
    list_display = ("visitor_name", "visitor_email", "assigned_department", "forwarded_to_department", "status", "created_at")
    list_filter = ("status", "assigned_department", "forwarded_to_department")
    search_fields = ("visitor_name", "visitor_email", "request_query")
    readonly_fields = ("created_at", "replied_at")


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title", "file_type", "processed", "chunk_count", "uploaded_at",
    )
    list_filter = ("file_type", "processed")
    readonly_fields = ("processed", "chunk_count", "processing_error", "uploaded_at")

    def save_model(self, request, obj, form, change):
        is_new_or_file_changed = "source_file" in form.changed_data or not change
        super().save_model(request, obj, form, change)

        if is_new_or_file_changed:
            if change:
                # Re-processing: clear any previously indexed data for this doc first.
                ingestion.remove_document(obj)
            try:
                n_chunks = ingestion.process_document(obj)
                obj.processed = True
                obj.chunk_count = n_chunks
                obj.processing_error = ""
                obj.save(update_fields=["processed", "chunk_count", "processing_error"])
                messages.success(
                    request,
                    f"'{obj.title}' processed successfully: {n_chunks} vector chunks "
                    f"embedded + page-index entries created.",
                )
            except Exception as e:  # noqa: BLE001
                obj.processed = False
                obj.processing_error = str(e)
                obj.save(update_fields=["processed", "processing_error"])
                messages.error(request, f"Failed to process '{obj.title}': {e}")

    def delete_model(self, request, obj):
        ingestion.remove_document(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            ingestion.remove_document(obj)
        super().delete_queryset(request, queryset)

