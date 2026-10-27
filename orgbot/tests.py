import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from orgbot.models import OrganizationProfile, Department, VisitorRequest
from orgbot.services import rag_engine, categorizer


class RAGPromptTruncationTests(TestCase):
    def test_build_prompt_truncates_large_context_before_llm_call(self):
        long_context = ["A" * 20000, "B" * 20000]
        prompt = rag_engine._build_prompt("What happened?", long_context)
        self.assertLess(len(prompt), 30000)
        self.assertIn("[truncated]", prompt)


class DashboardModeAndCategorizationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.profile = OrganizationProfile.get_solo()
        self.profile.dashboard_mode = True
        self.profile.save()

        self.gen_dept = Department.objects.create(
            department_name="General",
            department_email="general@spiher.ac.in",
        )
        self.lib_dept = Department.objects.create(
            department_name="Library",
            department_email="library@spiher.ac.in",
        )

    def test_categorize_query_fast_keyword(self):
        dept = categorizer.categorize_query("do you have The Da Vinci Code in library?")
        self.assertEqual(dept, self.lib_dept)

    def test_categorize_query_fallback(self):
        dept = categorizer.categorize_query("unrelated question without department keyword")
        self.assertEqual(dept, self.gen_dept)

    def test_chat_api_shows_visitor_form_when_dashboard_mode_true_and_missing_data(self):
        response = self.client.post(
            reverse("orgbot:chat_api"),
            data=json.dumps({"message": "you college library have The Da Vinci Code book"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("show_visitor_form"))
        self.assertIn("not in my Database", data.get("answer_html"))

    def test_submit_visitor_request_creates_ticket(self):
        payload = {
            "request_query": "you college library have The Da Vinci Code book",
            "name": "Giri",
            "email": "giri123@gmail.com",
        }
        response = self.client.post(
            reverse("orgbot:submit_visitor_request"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("message"), "You will get a response shortly via email.")

        req = VisitorRequest.objects.get(visitor_email="giri123@gmail.com")
        self.assertEqual(req.visitor_name, "Giri")
        self.assertEqual(req.assigned_department, self.lib_dept)
        self.assertEqual(req.status, "pending")


class DepartmentDashboardFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="library_user", password="password123", email="library@spiher.ac.in")
        self.lib_dept = Department.objects.create(
            department_name="Library",
            department_email="library@spiher.ac.in",
            user=self.user,
        )
        self.hostel_user = User.objects.create_user(username="hostel_user", password="password123", email="hostel@spiher.ac.in")
        self.hostel_dept = Department.objects.create(
            department_name="Hostel",
            department_email="hostel@spiher.ac.in",
            user=self.hostel_user,
        )

        self.visitor_req = VisitorRequest.objects.create(
            request_query="you college library have The Da Vinci Code book",
            visitor_name="Giri",
            visitor_email="giri123@gmail.com",
            assigned_department=self.lib_dept,
            status="pending",
        )

    def test_department_login_and_analytics(self):
        login_res = self.client.post(
            reverse("orgbot:dept_login"),
            data={"username": "library_user", "password": "password123"},
        )
        self.assertRedirects(login_res, reverse("orgbot:dept_analytics"))

        analytics_res = self.client.get(reverse("orgbot:dept_analytics"))
        self.assertEqual(analytics_res.status_code, 200)
        self.assertContains(analytics_res, "Library Department")

    def test_department_reply_action(self):
        self.client.login(username="library_user", password="password123")
        reply_url = reverse("orgbot:dept_request_detail", kwargs={"pk": self.visitor_req.pk})
        res = self.client.post(
            reply_url,
            data={
                "action": "reply",
                "reply_message": "yes we have the Da Vinci Code book. but the new version not the old one",
            },
        )
        self.assertRedirects(res, reverse("orgbot:dept_requests"))

        self.visitor_req.refresh_from_db()
        self.assertEqual(self.visitor_req.status, "cleared")
        self.assertEqual(self.visitor_req.reply_message, "yes we have the Da Vinci Code book. but the new version not the old one")

    def test_department_forward_and_accept_action(self):
        self.client.login(username="library_user", password="password123")
        detail_url = reverse("orgbot:dept_request_detail", kwargs={"pk": self.visitor_req.pk})
        res = self.client.post(
            detail_url,
            data={
                "action": "forward",
                "target_department_id": self.hostel_dept.pk,
            },
        )
        self.assertRedirects(res, reverse("orgbot:dept_requests"))

        self.visitor_req.refresh_from_db()
        self.assertEqual(self.visitor_req.status, "forwarded")
        self.assertEqual(self.visitor_req.forwarded_to_department, self.hostel_dept)

        # Login as Hostel admin and accept
        self.client.login(username="hostel_user", password="password123")
        accept_url = reverse("orgbot:dept_accept_forwarded_request", kwargs={"pk": self.visitor_req.pk})
        res_accept = self.client.post(accept_url)
        self.assertRedirects(res_accept, reverse("orgbot:dept_requests"))

        self.visitor_req.refresh_from_db()
        self.assertEqual(self.visitor_req.assigned_department, self.hostel_dept)
        self.assertIsNone(self.visitor_req.forwarded_to_department)
        self.assertEqual(self.visitor_req.status, "pending")
