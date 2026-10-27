from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User


class OrganizationProfile(models.Model):
    """
    Singleton-style model holding the organization's public info shown on
    the landing page hero section. Editable from the Django admin.
    """

    name = models.CharField(max_length=200, default="Your Organization")
    tagline = models.CharField(
        max_length=300,
        default="Building the future, one idea at a time.",
        help_text="Short catchy line shown under the organization name.",
    )
    about = models.TextField(
        default=(
            "We are a team of passionate innovators dedicated to delivering "
            "impactful solutions for our community and clients."
        ),
        help_text="Short paragraph shown in the hero section.",
    )
    about_point_1 = models.CharField(
        max_length=200,
        default="Committed to innovation and quality",
        help_text="First bullet point shown in the About section.",
    )
    about_point_2 = models.CharField(
        max_length=200,
        default="Focused on community impact and trust",
        help_text="Second bullet point shown in the About section.",
    )
    about_point_3 = models.CharField(
        max_length=200,
        default="Delivering lasting value through collaboration",
        help_text="Third bullet point shown in the About section.",
    )
    about_image_1 = models.ImageField(
        upload_to="org_images/", blank=True, null=True,
        help_text="First image shown in the About section.",
    )
    about_image_2 = models.ImageField(
        upload_to="org_images/", blank=True, null=True,
        help_text="Second image shown in the About section.",
    )
    hero_image = models.ImageField(
        upload_to="org_images/", blank=True, null=True,
        help_text="Main hero banner image. Leave blank to use a placeholder.",
    )
    gallery_image_1 = models.ImageField(upload_to="org_images/", blank=True, null=True)
    gallery_image_2 = models.ImageField(upload_to="org_images/", blank=True, null=True)
    contact_email = models.EmailField(blank=True, default="info@spiher.ac.in")
    website_url = models.URLField(
        blank=True,
        default="https://spiher.ac.in/",
        help_text="Main website URL (e.g. https://spiher.ac.in/).",
    )
    about_url = models.URLField(
        blank=True,
        default="https://spiher.ac.in/about-us/",
        help_text=(
            "URL of the About Us page. Shown in fallback responses when the "
            "bot cannot find a specific answer (e.g. https://spiher.ac.in/about-us/)."
        ),
    )
    contact_url = models.URLField(
        blank=True,
        default="https://spiher.ac.in/contact-us/",
        help_text=(
            "URL of the Contact page. Shown in fallback responses when the "
            "bot cannot find a specific answer (e.g. https://spiher.ac.in/contact-us/)."
        ),
    )
    theme_color = models.CharField(
        max_length=20,
        default="teal",
        choices=[
            ("teal", "Teal / Emerald"),
            ("indigo", "Indigo / Violet"),
            ("sunset", "Coral / Amber"),
            ("ocean", "Blue / Cyan"),
            ("rose", "Rose / Pink"),
        ],
        help_text="Pick a light color theme for the site (no dark themes).",
    )
    dashboard_mode = models.BooleanField(
        default=False,
        verbose_name="Dashboard Mode",
        help_text="When TRUE (ON), unresolved bot queries will prompt visitors for their details to route to department admins.",
    )

    class Meta:
        verbose_name = "Organization Profile"
        verbose_name_plural = "Organization Profile"

    def save(self, *args, **kwargs):
        # Enforce singleton pattern - only one profile row should exist.
        if not self.pk and OrganizationProfile.objects.exists():
            existing = OrganizationProfile.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"pk": 1})
        return obj


def validate_file_extension(value):
    allowed = (".txt", ".json")
    name = value.name.lower()
    if not name.endswith(allowed):
        raise ValidationError("Only .txt (plain text) or .json files are supported.")


class KnowledgeDocument(models.Model):
    """
    A raw source file uploaded by the admin (organization data).
    On save, this is processed into:
      1. Chunk + embed -> ChromaDB (vector RAG method)
      2. Structured entries -> page_index.json (fast fallback method)
    """

    FILE_TYPE_CHOICES = [
        ("text", "Plain Text (.txt)"),
        ("json", "JSON (.json)"),
    ]

    title = models.CharField(max_length=200)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    source_file = models.FileField(
        upload_to="knowledge_sources/", validators=[validate_file_extension]
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)
    chunk_count = models.PositiveIntegerField(default=0)
    processing_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        status = "processed" if self.processed else "pending"
        return f"{self.title} ({self.file_type}, {status})"


class Department(models.Model):
    """
    College / Organization department created by superadmin.
    Associated with a Django User for login into the Department Dashboard.
    """
    department_name = models.CharField(max_length=100, unique=True)
    department_email = models.EmailField()
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="department_profile", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["department_name"]

    def __str__(self):
        return self.department_name


class VisitorRequest(models.Model):
    """
    Visitor query request recorded when RAG bot cannot find data in DB
    and dashboard_mode is TRUE.
    """
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("cleared", "Cleared"),
        ("forwarded", "Forwarded"),
        ("deleted", "Deleted"),
    ]

    request_query = models.TextField()
    visitor_name = models.CharField(max_length=150)
    visitor_email = models.EmailField()
    assigned_department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="assigned_requests"
    )
    forwarded_to_department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="forwarded_requests"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reply_message = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.visitor_name} ({self.assigned_department.department_name}): {self.request_query[:40]}"

