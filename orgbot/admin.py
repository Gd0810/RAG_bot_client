from django.contrib import admin, messages

from .models import OrganizationProfile, KnowledgeDocument
from .services import ingestion


@admin.register(OrganizationProfile)
class OrganizationProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "tagline", "theme_color")

    fieldsets = (
        ("Basic Info", {"fields": ("name", "tagline", "about")}),
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
