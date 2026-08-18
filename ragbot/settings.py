"""
Django settings for ragbot project (Organization RAG Chatbot).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file at project root
load_dotenv(BASE_DIR / ".env")

# -----------------------------------------------------------------------
# Core / Security
# -----------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-CHANGE-ME-please-set-a-real-secret-key-in-.env",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()
]

# -----------------------------------------------------------------------
# Applications
# -----------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "orgbot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ragbot.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "orgbot.context_processors.organization_profile",
            ],
        },
    },
]

WSGI_APPLICATION = "ragbot.wsgi.application"

# -----------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# -----------------------------------------------------------------------
# Password validation
# -----------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -----------------------------------------------------------------------
# Internationalization
# -----------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------------------------
# Static & Media files
# -----------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------------------------------------------------
# RAG / Chroma / Page-index storage locations
# -----------------------------------------------------------------------
CHROMA_PERSIST_DIR = str(BASE_DIR / "chroma_store")
CHROMA_COLLECTION_NAME = os.environ.get("CHROMA_COLLECTION_NAME", "organization_data")

PAGE_INDEX_DIR = BASE_DIR / "media" / "page_index"
PAGE_INDEX_FILE = PAGE_INDEX_DIR / "page_index.json"

# -----------------------------------------------------------------------
# NVIDIA NIM (build.nvidia.com) LLM configuration
# Primary model uses NVIDIA_API_KEY_PRIMARY (or NVIDIA_API_KEY).
# Fallback model uses NVIDIA_API_KEY_FALLBACK (defaults to primary key if unset).
# -----------------------------------------------------------------------

def _get_nvidia_model(env_name: str, default: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        # Avoid known end-of-life model IDs from older project defaults.
        if value == "mistralai/mixtral-8x7b-instruct-v0.1":
            return "meta/llama-3.1-8b-instruct"
        return value
    return default


NVIDIA_API_BASE_URL = os.environ.get(
    "NVIDIA_API_BASE_URL", "https://integrate.api.nvidia.com/v1"
)

# API Keys: Primary and Fallback (allows 2 separate accounts/keys)
NVIDIA_API_KEY_PRIMARY = os.environ.get(
    "NVIDIA_API_KEY_PRIMARY", os.environ.get("NVIDIA_API_KEY", "")
).strip()
NVIDIA_API_KEY_FALLBACK = os.environ.get(
    "NVIDIA_API_KEY_FALLBACK", ""
).strip() or NVIDIA_API_KEY_PRIMARY

# Legacy alias for backward compatibility
NVIDIA_API_KEY = NVIDIA_API_KEY_PRIMARY

NVIDIA_MODEL_PRIMARY = _get_nvidia_model(
    "NVIDIA_MODEL_PRIMARY", "nvidia/llama-3.1-nemotron-70b-instruct"
)
NVIDIA_MODEL_FALLBACK = _get_nvidia_model(
    "NVIDIA_MODEL_FALLBACK", "meta/llama-3.1-8b-instruct"
)
NVIDIA_REQUEST_TIMEOUT = int(os.environ.get("NVIDIA_REQUEST_TIMEOUT", "30"))

# -----------------------------------------------------------------------
# RAG tuning
# -----------------------------------------------------------------------
VECTOR_TOP_K = int(os.environ.get("VECTOR_TOP_K", "4"))
# Chroma returns a "distance" (lower = more similar) for the hashing embedding.
# If the best distance is above this threshold, we treat the vector store as
# having "no relevant answer" and fall back to the page-index method.
VECTOR_DISTANCE_THRESHOLD = float(os.environ.get("VECTOR_DISTANCE_THRESHOLD", "0.90"))
PAGE_INDEX_TOP_K = int(os.environ.get("PAGE_INDEX_TOP_K", "3"))
