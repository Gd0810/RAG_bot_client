import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings

from .models import Department, VisitorRequest, OrganizationProfile

logger = logging.getLogger(__name__)


def get_current_department(user):
    """Helper to retrieve department object for logged-in user."""
    if not user.is_authenticated:
        return None
    try:
        return user.department_profile
    except Department.DoesNotExist:
        if user.is_superuser:
            # Fallback for superuser: return or create General department
            general, _ = Department.objects.get_or_create(
                department_name="General",
                defaults={
                    "department_email": user.email or "admin@spiher.ac.in",
                    "user": user,
                    "is_active": True,
                },
            )
            return general
        return None


def department_login(request):
    if request.user.is_authenticated:
        dept = get_current_department(request.user)
        if dept:
            return redirect("orgbot:dept_analytics")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            dept = get_current_department(user)
            if dept:
                messages.success(request, f"Welcome back, {dept.department_name} Department Admin!")
                return redirect("orgbot:dept_analytics")
            else:
                messages.error(request, "This account is not associated with an active department profile.")
                logout(request)
        else:
            messages.error(request, "Invalid department username or password.")

    profile = OrganizationProfile.get_solo()
    return render(request, "orgbot/department/login.html", {"profile": profile})


@login_required
def department_logout(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("orgbot:dept_login")


@login_required
def analytics_dashboard(request):
    dept = get_current_department(request.user)
    if not dept:
        messages.error(request, "Department profile not found.")
        return redirect("orgbot:dept_login")

    profile = OrganizationProfile.get_solo()

    # Query metrics
    assigned_qs = VisitorRequest.objects.filter(assigned_department=dept)
    
    total_received = assigned_qs.count()
    pending_count = assigned_qs.filter(status="pending").count()
    cleared_count = assigned_qs.filter(status="cleared").count()
    deleted_count = assigned_qs.filter(status="deleted").count()
    forwarded_out_count = assigned_qs.filter(status="forwarded").count()

    incoming_forwarded_count = VisitorRequest.objects.filter(
        forwarded_to_department=dept, status="forwarded"
    ).count()

    recent_requests = assigned_qs.exclude(status="deleted")[:5]

    context = {
        "department": dept,
        "profile": profile,
        "active_tab": "analytics",
        "total_received": total_received,
        "pending_count": pending_count,
        "cleared_count": cleared_count,
        "deleted_count": deleted_count,
        "forwarded_out_count": forwarded_out_count,
        "incoming_forwarded_count": incoming_forwarded_count,
        "recent_requests": recent_requests,
    }
    return render(request, "orgbot/department/analytics.html", context)


@login_required
def requests_list(request):
    dept = get_current_department(request.user)
    if not dept:
        return redirect("orgbot:dept_login")

    profile = OrganizationProfile.get_solo()
    status_filter = request.GET.get("status", "all")

    # List requests currently assigned to this department (excluding forwarded away & deleted)
    qs = VisitorRequest.objects.filter(assigned_department=dept).exclude(status="deleted")
    if status_filter in ["pending", "cleared"]:
        qs = qs.filter(status=status_filter)

    incoming_forwarded_count = VisitorRequest.objects.filter(
        forwarded_to_department=dept, status="forwarded"
    ).count()

    context = {
        "department": dept,
        "profile": profile,
        "active_tab": "requests",
        "requests": qs,
        "status_filter": status_filter,
        "incoming_forwarded_count": incoming_forwarded_count,
    }
    return render(request, "orgbot/department/requests.html", context)


@login_required
def request_detail(request, pk):
    dept = get_current_department(request.user)
    if not dept:
        return redirect("orgbot:dept_login")

    visitor_req = get_object_or_404(VisitorRequest, pk=pk, assigned_department=dept)
    profile = OrganizationProfile.get_solo()
    other_departments = Department.objects.filter(is_active=True).exclude(pk=dept.pk)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "reply":
            reply_msg = request.POST.get("reply_message", "").strip()
            if not reply_msg:
                messages.error(request, "Reply message cannot be empty.")
            else:
                formatted_date = visitor_req.created_at.strftime("%d/%m/%Y - %I:%M%p").lower()
                org_name = profile.name or "our institution"
                
                # Format required by prompt:
                # "we are form {{ profile.name}} with department of {{department.name}} you ask {{request_query}} on {{date}} the response with department is - {{reply_message}}"
                email_subject = f"Response from {dept.department_name} Department - {org_name}"
                email_body = (
                    f"We are from {org_name} with department of {dept.department_name}. "
                    f"You asked '{visitor_req.request_query}' on {formatted_date}.\n\n"
                    f"The response from department is -\n\"{reply_msg}\"\n\n"
                    f"Best regards,\n{dept.department_name} Department\n{org_name}"
                )

                from django.core.mail import EmailMessage

                from_email_addr = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
                if from_email_addr and "@" in from_email_addr:
                    sender = f"{dept.department_name} Department <{from_email_addr}>"
                else:
                    sender = dept.department_email

                try:
                    email_msg = EmailMessage(
                        subject=email_subject,
                        body=email_body,
                        from_email=sender,
                        to=[visitor_req.visitor_email],
                        reply_to=[dept.department_email],
                    )
                    email_msg.send(fail_silently=False)
                    messages.success(request, f"Reply successfully sent to {visitor_req.visitor_email}!")
                except Exception as e:
                    logger.error("Failed to send reply email: %s", e)
                    messages.warning(
                        request,
                        f"Reply saved and marked as cleared, but SMTP email could not be sent (Error: {e})."
                    )


                visitor_req.reply_message = reply_msg
                visitor_req.status = "cleared"
                visitor_req.replied_at = timezone.now()
                visitor_req.save()
                return redirect("orgbot:dept_requests")

        elif action == "forward":
            target_dept_id = request.POST.get("target_department_id")
            if not target_dept_id:
                messages.error(request, "Please select a target department to forward the request.")
            else:
                target_dept = get_object_or_404(Department, pk=target_dept_id, is_active=True)
                visitor_req.forwarded_to_department = target_dept
                visitor_req.status = "forwarded"
                visitor_req.save()
                messages.success(request, f"Request forwarded to {target_dept.department_name} Department.")
                return redirect("orgbot:dept_requests")

        elif action == "delete":
            visitor_req.status = "deleted"
            visitor_req.save()
            messages.success(request, "Request deleted successfully.")
            return redirect("orgbot:dept_requests")

    incoming_forwarded_count = VisitorRequest.objects.filter(
        forwarded_to_department=dept, status="forwarded"
    ).count()

    context = {
        "department": dept,
        "profile": profile,
        "active_tab": "requests",
        "req": visitor_req,
        "other_departments": other_departments,
        "incoming_forwarded_count": incoming_forwarded_count,
    }
    return render(request, "orgbot/department/request_detail.html", context)


@login_required
def forward_requests_list(request):
    dept = get_current_department(request.user)
    if not dept:
        return redirect("orgbot:dept_login")

    profile = OrganizationProfile.get_solo()
    forwarded_requests = VisitorRequest.objects.filter(
        forwarded_to_department=dept, status="forwarded"
    )

    incoming_forwarded_count = forwarded_requests.count()

    context = {
        "department": dept,
        "profile": profile,
        "active_tab": "forward_requests",
        "forwarded_requests": forwarded_requests,
        "incoming_forwarded_count": incoming_forwarded_count,
    }
    return render(request, "orgbot/department/forward_requests.html", context)


@login_required
def accept_forwarded_request(request, pk):
    dept = get_current_department(request.user)
    if not dept:
        return redirect("orgbot:dept_login")

    visitor_req = get_object_or_404(VisitorRequest, pk=pk, forwarded_to_department=dept, status="forwarded")
    
    if request.method == "POST":
        visitor_req.assigned_department = dept
        visitor_req.forwarded_to_department = None
        visitor_req.status = "pending"
        visitor_req.save()
        messages.success(request, f"Request from {visitor_req.visitor_name} accepted into {dept.department_name} Requests.")

    return redirect("orgbot:dept_requests")
