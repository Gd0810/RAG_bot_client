import json
import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .models import OrganizationProfile
from .services import rag_engine
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

    return JsonResponse({
        "answer_html": render_answer_html(result["answer"], extra_urls=result.get("urls", [])),
        "method": result["method"],
        "sources": result["sources"],
        "urls": result.get("urls", []),
        "model_used": result["model_used"],
    })
