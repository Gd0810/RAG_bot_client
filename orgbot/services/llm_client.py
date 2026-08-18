"""
Client for NVIDIA's free-tier hosted models on build.nvidia.com.

The API is OpenAI-chat-completions compatible, so we just POST to
`{NVIDIA_API_BASE_URL}/chat/completions`.

Two models are configured with separate API keys in .env:
- NVIDIA_MODEL_PRIMARY / NVIDIA_API_KEY_PRIMARY
- NVIDIA_MODEL_FALLBACK / NVIDIA_API_KEY_FALLBACK

If the primary model call fails or times out for any reason, we
automatically retry with the fallback model using its dedicated API key.
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def _call_model(model: str, api_key: str, messages: list, temperature: float = 0.3, max_tokens: int = 700) -> str:
    if not api_key:
        raise LLMError(
            f"NVIDIA API key is not configured for model '{model}'. "
            "Please check NVIDIA_API_KEY_PRIMARY / NVIDIA_API_KEY_FALLBACK in your .env file."
        )

    url = f"{settings.NVIDIA_API_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    response = requests.post(
        url, headers=headers, json=payload, timeout=settings.NVIDIA_REQUEST_TIMEOUT
    )
    if response.status_code != 200:
        raise LLMError(f"NVIDIA API error ({model}): {response.status_code} {response.text[:300]}")

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected NVIDIA API response shape from {model}: {e}")


def generate_answer(system_prompt: str, user_prompt: str) -> dict:
    """
    Tries the primary model with NVIDIA_API_KEY_PRIMARY, 
    then the fallback model with NVIDIA_API_KEY_FALLBACK.
    Returns {"answer": str, "model_used": str} or raises LLMError if both fail.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    configs_to_try = [
        ("primary", settings.NVIDIA_MODEL_PRIMARY, settings.NVIDIA_API_KEY_PRIMARY),
        ("fallback", settings.NVIDIA_MODEL_FALLBACK, settings.NVIDIA_API_KEY_FALLBACK),
    ]

    last_error = None
    for label, model, api_key in configs_to_try:
        if not model:
            continue
        if not api_key:
            logger.warning("Skipping %s model (%s): API key is empty.", label, model)
            continue
        try:
            answer = _call_model(model=model, api_key=api_key, messages=messages)
            return {"answer": answer, "model_used": model}
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM call failed for %s model (%s): %s", label, model, e)
            last_error = e
            continue

    raise LLMError(f"Both NVIDIA models failed. Last error: {last_error}")
