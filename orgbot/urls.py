from django.urls import path
from . import views, department_views

app_name = "orgbot"

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("api/chat/", views.chat_api, name="chat_api"),
    path("api/submit-visitor-request/", views.submit_visitor_request, name="submit_visitor_request"),

    # Department Dashboard URLs
    path("department/login/", department_views.department_login, name="dept_login"),
    path("department/logout/", department_views.department_logout, name="dept_logout"),
    path("department/dashboard/", department_views.analytics_dashboard, name="dept_analytics"),
    path("department/dashboard/requests/", department_views.requests_list, name="dept_requests"),
    path("department/dashboard/requests/<int:pk>/", department_views.request_detail, name="dept_request_detail"),
    path("department/dashboard/forward-requests/", department_views.forward_requests_list, name="dept_forward_requests"),
    path("department/dashboard/forward-requests/<int:pk>/accept/", department_views.accept_forwarded_request, name="dept_accept_forwarded_request"),
]

