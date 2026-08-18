from django.test import TestCase

from orgbot.services import rag_engine


class RAGPromptTruncationTests(TestCase):
    def test_build_prompt_truncates_large_context_before_llm_call(self):
        long_context = ["A" * 20000, "B" * 20000]

        prompt = rag_engine._build_prompt("What happened?", long_context)

        self.assertLess(len(prompt), 30000)
        self.assertIn("[truncated]", prompt)
