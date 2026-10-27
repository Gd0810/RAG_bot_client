import json
import logging
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .models import OrganizationProfile, VisitorRequest
from .services import rag_engine, categorizer
from .services.utils import render_answer_html

logger = logging.getLogger(__name__)


def landing_page(request):
    profile = OrganizationProfile.get_solo()
    return render(request, "orgbot/landing.html", {"profile": profile})


@csrf_protect
@require_http_methods(["POST"])
def chat_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    message = (payload.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    if len(message) > 1000:
        return JsonResponse({"error": "Message is too long (max 1000 characters)."}, status=400)

    result = rag_engine.answer_question(message)
    show_visitor_form = result.get("show_visitor_form", False)
    query_text = result.get("query", message)
    extra_urls = [] if show_visitor_form else result.get("urls", [])

    return JsonResponse({
        "answer_html": render_answer_html(
            result["answer"],
            extra_urls=extra_urls,
            show_visitor_form=show_visitor_form,
            query=query_text,
        ),
        "method": result["method"],
        "sources": result["sources"],
        "urls": extra_urls,
        "model_used": result["model_used"],
        "show_visitor_form": show_visitor_form,
        "query": query_text,
    })



@csrf_protect
@require_http_methods(["POST"])
def submit_visitor_request(request):
    """
    Handles form submission when a visitor requests human assistance
    for an unresolved RAG query in dashboard mode.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request payload."}, status=400)

    request_query = (payload.get("request_query") or "").strip()
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()

    if not request_query or not name or not email:
        return JsonResponse({"error": "Name, email, and question details are required."}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Please enter a valid email address."}, status=400)

    # Categorize query to target department
    target_dept = categorizer.categorize_query(request_query)
    if not target_dept:
        return JsonResponse({"error": "System is unable to process departments at this moment."}, status=500)

    visitor_req = VisitorRequest.objects.create(
        request_query=request_query,
        visitor_name=name,
        visitor_email=email,
        assigned_department=target_dept,
        status="pending",
    )

    logger.info(
        "Created visitor request #%d for '%s' (%s) routed to department '%s'",
        visitor_req.pk,
        name,
        email,
        target_dept.department_name,
    )

    return JsonResponse({
        "success": True,
        "message": "You will get a response shortly via email.",
        "department": target_dept.department_name,
    })

