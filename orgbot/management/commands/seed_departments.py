from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils.text import slugify
from orgbot.models import Department, OrganizationProfile


class Command(BaseCommand):
    help = "Seeds initial college departments and department admin logins."

    DEFAULT_DEPARTMENTS = [
        ("General", "general@spiher.ac.in"),
        ("Admission", "admission@spiher.ac.in"),
        ("Studies", "studies@spiher.ac.in"),
        ("Hostel", "hostel@spiher.ac.in"),
        ("Canteen", "canteen@spiher.ac.in"),
        ("Cleaning", "cleaning@spiher.ac.in"),
        ("Library", "library@spiher.ac.in"),
        ("Sports", "sports@spiher.ac.in"),
        ("Travel", "travel@spiher.ac.in"),
        ("Maintenance", "maintenance@spiher.ac.in"),
    ]

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Seeding initial departments..."))

        # Ensure OrganizationProfile exists
        profile = OrganizationProfile.get_solo()
        profile.save()

        default_password = "password123"

        for dept_name, dept_email in self.DEFAULT_DEPARTMENTS:
            username = slugify(dept_name).replace("-", "_")
            
            # Create or update user
            user, u_created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": dept_email,
                    "is_staff": True,
                }
            )
            user.set_password(default_password)
            user.email = dept_email
            user.is_staff = True
            user.save()

            # Create or update department
            dept, d_created = Department.objects.get_or_create(
                department_name=dept_name,
                defaults={
                    "department_email": dept_email,
                    "user": user,
                    "is_active": True,
                }
            )
            if not d_created:
                dept.department_email = dept_email
                dept.user = user
                dept.is_active = True
                dept.save()

            status_str = "Created" if d_created else "Updated"
            self.stdout.write(
                f"  - {status_str} Department: {dept_name} (User: '{username}', Pass: '{default_password}')"
            )

        self.stdout.write(self.style.SUCCESS("Departments seeded successfully!"))
