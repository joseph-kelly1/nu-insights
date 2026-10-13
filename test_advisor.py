"""Offline tests for the OpenRouter integration: no API key, network, or courses.db needed.

Run: .venv/bin/python -m unittest -v
"""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

import httpx2 as httpx
import openai

import advisor

COURSE = {
    "id": 1, "department_code": "cs", "number": "3000", "title": "Algorithms and Data", "credits": 4.0,
    "description": "Introduces algorithms.",
    "prerequisites": {"type": "AND", "courses": [
        {"type": "OR", "courses": [{"course": "CS 2100"}, {"course": "CS 2510"}]},
        {"type": "OR", "courses": [{"course": "CS 1800"}, {"course": "EECE 2160"}]},
    ]},
    "corequisites": ["CS 3001"],
    "attributes": ["NUpath Analyzing/Using Data"],
}
PLANS = [
    {"major": "BSCS", "major_name": "Computer Science", "plan_name": "Four Years, One Co-op", "year": 2, "term": "Spring"},
    {"major": "BSDS", "major_name": "Data Science", "plan_name": "Five Years, Two Co-ops", "year": 3, "term": "Fall"},
]
MARKDOWN = "## CS 3000\n\n**Take it** in year 2.\n\n- skill"


def completion(content=MARKDOWN, finish="stop", model="inclusionai/ling-3.1-flash"):
    return {"id": "gen-1", "model": model, "choices": [
        {"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}]}


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.reply = lambda: httpx.Response(200, json=completion())

        def handler(request):
            self.sent.append(json.loads(request.content))
            return self.reply()

        client = openai.OpenAI(api_key="test", base_url="https://openrouter.ai/api/v1", max_retries=0,
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        for name, value in [
            ("_client", lambda: client),
            ("API_KEY", "test"),
            ("FALLBACK_MODELS", ["nvidia/nemotron-3.5-lightning:free"]),
            ("lookup_course", lambda d, n: dict(COURSE) if (d.lower(), n) == ("cs", "3000") else None),
            ("lookup_schedule_context", lambda d, n: PLANS),
        ]:
            patcher = mock.patch.object(advisor, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.http = advisor.app.test_client()

    def analyze(self, body={"dept": "CS", "number": "3000"}):
        return self.http.post("/api/analyze", json=body)

    def test_request_is_grounded_free_only_and_returns_markdown(self):
        res = self.analyze()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json, {"analysis": MARKDOWN, "model": "inclusionai/ling-3.1-flash"})

        sent = self.sent[0]
        self.assertEqual(sent["model"], "inclusionai/ling-3.1-flash")
        self.assertEqual(sent["models"], ["nvidia/nemotron-3.5-lightning:free"])
        self.assertEqual(sent["provider"]["max_price"], {"prompt": 0, "completion": 0, "request": 0})
        self.assertTrue(sent["provider"]["require_parameters"])
        self.assertEqual(sent["reasoning"], {"enabled": False, "exclude": True})
        self.assertEqual([m["role"] for m in sent["messages"]], ["system", "user"])
        prompt = sent["messages"][1]["content"]
        for fact in ["((CS 2100 OR CS 2510) AND (CS 1800 OR EECE 2160))", "Corequisites: CS 3001",
                     "NUpath Analyzing/Using Data", 'Computer Science (BSCS), "Four Years, One Co-op": Year 2, Spring',
                     'Data Science (BSDS), "Five Years, Two Co-ops": Year 3, Fall']:
            self.assertIn(fact, prompt)

    def test_fallback_success_does_not_downgrade_later_requests(self):
        self.reply = lambda: httpx.Response(200, json=completion(model="nvidia/nemotron-3.5-lightning:free"))
        self.assertEqual(self.analyze().json["model"], "nvidia/nemotron-3.5-lightning:free")
        self.analyze()
        self.assertEqual([s["model"] for s in self.sent], ["inclusionai/ling-3.1-flash"] * 2)

    def test_empty_fallback_list_omits_models(self):
        with mock.patch.object(advisor, "FALLBACK_MODELS", []):
            self.analyze()
        self.assertNotIn("models", self.sent[0])

    def test_invalid_or_unknown_course_never_calls_provider(self):
        for body in [None, [], {"dept": "cs"}, {"dept": 5, "number": "3000"}, {"dept": "cs", "number": 3000},
                     {"dept": "cs'; --", "number": "3000"}, {"dept": "", "number": ""}]:
            with self.subTest(body=body):
                self.assertEqual(self.analyze(body).status_code, 400)
        self.assertEqual(self.http.post("/api/analyze", data="not json").status_code, 400)
        res = self.analyze({"dept": "cs", "number": "9999"})
        self.assertEqual((res.status_code, res.json["code"]), (404, "course_not_found"))
        self.assertEqual(self.sent, [])

    def test_missing_key_keeps_other_routes_working(self):
        with mock.patch.object(advisor, "API_KEY", ""):
            res = self.analyze()
            self.assertEqual((res.status_code, res.json["code"]), (503, "ai_not_configured"))
            self.assertFalse(self.http.get("/api/health").json["ai_configured"])
            self.assertEqual(self.http.get("/api/course/cs/3000").status_code, 200)
        self.assertEqual(self.sent, [])

    def test_upstream_failures_map_to_safe_json(self):
        def error(status, **kw):
            return lambda: httpx.Response(status, json={"error": {"code": status, "message": "RAW provider detail"}}, **kw)

        def raise_(exc):
            def reply():
                raise exc
            return reply

        cases = [
            (error(429, headers={"retry-after": "7"}), 429, "rate_limited"),
            (error(401), 503, "ai_misconfigured"),
            (error(402), 503, "ai_misconfigured"),
            (error(404), 503, "ai_unavailable"),
            (error(503), 503, "ai_unavailable"),
            (error(500), 502, "upstream_error"),
            (raise_(httpx.ReadTimeout("slow")), 504, "ai_timeout"),
            (raise_(httpx.ConnectError("down")), 503, "ai_unavailable"),
            (lambda: httpx.Response(200, json={"error": {"code": 429, "message": "RAW provider detail"}}), 429, "rate_limited"),
            (lambda: httpx.Response(200, json={"id": "gen-1", "model": "m", "choices": [
                {"index": 0, "finish_reason": "error", "message": {"role": "assistant", "content": ""},
                 "error": {"code": 502, "message": "RAW provider detail"}}]}), 503, "ai_unavailable"),
            (lambda: httpx.Response(200, json=completion("   ")), 502, "bad_response"),
            (lambda: httpx.Response(200, json=completion("partial", "length")), 502, "incomplete_response"),
            (lambda: httpx.Response(200, json={"id": "gen-1", "model": "m"}), 502, "bad_response"),
        ]
        for reply, status, code in cases:
            with self.subTest(code=code, status=status):
                self.reply = reply
                res = self.analyze()
                self.assertEqual((res.status_code, res.json["code"]), (status, code))
                self.assertNotIn("RAW", res.get_data(as_text=True))
                self.assertNotIn("analysis", res.json)

        self.reply = cases[0][0]
        self.assertEqual(self.analyze().json["retry_after_seconds"], 7)

    def test_unexpected_failure_returns_generic_json(self):
        with mock.patch.object(advisor, "build_prompt", side_effect=KeyError("boom")):
            res = self.analyze()
        self.assertEqual((res.status_code, res.json["code"]), (500, "internal_error"))


class ConfigTest(unittest.TestCase):
    BASE = {"OPENROUTER_MODEL": "inclusionai/ling-3.1-flash", "OPENROUTER_FALLBACK_MODELS": "",
            "OPENROUTER_REASONING_ENABLED": "false", "OPENROUTER_MAX_TOKENS": "2048", "OPENROUTER_TIMEOUT_SECONDS": "35"}

    def load(self, **overrides):
        env = {**os.environ, **self.BASE, **overrides}
        return subprocess.run([sys.executable, "-c", "import advisor; print(advisor.FALLBACK_MODELS)"],
                              cwd=os.path.dirname(os.path.abspath(__file__)), env=env, capture_output=True, text=True)

    def test_fallbacks_are_trimmed_deduplicated_and_exclude_primary(self):
        result = self.load(OPENROUTER_FALLBACK_MODELS=" a/b:free , a/b:free,inclusionai/ling-3.1-flash,,")
        self.assertEqual(result.stdout.strip(), "['a/b:free']")
        self.assertEqual(self.load().stdout.strip(), "[]")

    def test_invalid_settings_fail_startup(self):
        for key, value in [("OPENROUTER_REASONING_ENABLED", "yes"), ("OPENROUTER_MAX_TOKENS", "0"),
                           ("OPENROUTER_MAX_TOKENS", "lots"), ("OPENROUTER_TIMEOUT_SECONDS", "-1"),
                           ("OPENROUTER_FALLBACK_MODELS", "not a model")]:
            with self.subTest(**{key: value}):
                self.assertNotEqual(self.load(**{key: value}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
