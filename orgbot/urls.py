from django.urls import path
from . import views

app_name = "orgbot"

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("api/chat/", views.chat_api, name="chat_api"),
]
