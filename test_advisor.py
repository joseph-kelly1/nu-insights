"""Offline tests for the AI integrations: no API key, network, or courses.db needed.

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


def completion(content=MARKDOWN, finish="stop", model="google/gemma-4-31b-it:free"):
    return {"id": "gen-1", "model": model, "choices": [
        {"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}]}


class ApiTest(unittest.TestCase):
    """Patches the default OpenRouter client and the course database for every API test."""

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
            ("PRIMARY_MODEL", "google/gemma-4-31b-it:free"),
            ("FALLBACK_MODELS", ["openrouter/free"]),
            ("lookup_course", lambda d, n: dict(COURSE) if (d.lower(), n) == ("cs", "3000") else None),
            ("lookup_schedule_context", lambda d, n: PLANS),
            ("lookup_plan_dataset", lambda: {"catalog_year": None, "current_catalog_year": None, "plan_count": 2, "historical": False}),
        ]:
            patcher = mock.patch.object(advisor, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.http = advisor.app.test_client()

    def analyze(self, body={"dept": "CS", "number": "3000"}):
        return self.http.post("/api/analyze", json=body)


class AnalyzeTest(ApiTest):
    def test_request_is_grounded_free_only_and_returns_markdown(self):
        res = self.analyze()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json, {"analysis": MARKDOWN, "model": "google/gemma-4-31b-it:free"})

        sent = self.sent[0]
        self.assertEqual(sent["model"], "google/gemma-4-31b-it:free")
        self.assertEqual(sent["models"], ["openrouter/free"])
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
        self.reply = lambda: httpx.Response(200, json=completion(model="openrouter/free"))
        self.assertEqual(self.analyze().json["model"], "openrouter/free")
        self.analyze()
        self.assertEqual([s["model"] for s in self.sent], ["google/gemma-4-31b-it:free"] * 2)

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


SECRET = "sk-SECRET-marker-0123456789"
CUSTOM = {  # provider: (model, upstream URL, auth header, auth value)
    "openai": ("gpt-6-luna", "https://api.openai.com/v1/responses", "authorization", f"Bearer {SECRET}"),
    "anthropic": ("claude-opus-5-5", "https://api.anthropic.com/v1/messages", "x-api-key", SECRET),
    "gemini": ("gemini-3.5-flash",
               "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent",
               "x-goog-api-key", SECRET),
    "openrouter": ("vendor/paid-model", "https://openrouter.ai/api/v1/chat/completions", "authorization", f"Bearer {SECRET}"),
}


def custom(provider, model=None, key=SECRET, **extra):
    return {"dept": "cs", "number": "3000",
            "ai": {"mode": "custom", "provider": provider, "api_key": key, "model": model or CUSTOM[provider][0], **extra}}


def ok_body(provider, model):
    """A successful native response from each provider, including non-text parts that must be skipped."""
    return {
        "openai": {"id": "resp_1", "model": model, "status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": MARKDOWN}]}],
            "usage": {"input_tokens": 9, "output_tokens": 7, "output_tokens_details": {"reasoning_tokens": 2}}},
        "anthropic": {"id": "msg_1", "model": model, "stop_reason": "end_turn", "content": [
            {"type": "thinking", "thinking": "THOUGHT"}, {"type": "text", "text": MARKDOWN}]},
        "gemini": {"responseId": "r1", "modelVersion": model, "candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": "THOUGHT", "thought": True}, {"text": MARKDOWN}]}}]},
        "openrouter": completion(model=model),
    }[provider]


def reply(status, body=None, **kw):
    return lambda request: httpx.Response(status, json=body, **kw)


def fail(exc):
    def reply(request):
        raise exc
    return reply


class CustomAITest(ApiTest):
    def setUp(self):
        super().setUp()
        self.upstream, self.clients = [], []
        self.custom_reply = reply(200, {})

        def handler(request):
            self.upstream.append(request)
            return self.custom_reply(request)

        real_client = httpx.Client

        def client(**kw):  # every custom call must build, then close, its own client
            self.clients.append(real_client(transport=httpx.MockTransport(handler), **kw))
            return self.clients[-1]

        for patcher in [mock.patch.object(httpx, "Client", client),
                        mock.patch.dict(advisor.ai_providers._cheapest_rung, clear=True)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def posts(self):
        """Generation requests, skipping OpenRouter's catalog lookup."""
        return [json.loads(r.content) for r in self.upstream if r.method == "POST"]

    def assert_clients_closed(self):
        self.assertTrue(self.clients and all(c.is_closed for c in self.clients))

    def test_each_provider_gets_its_key_model_and_grounded_prompt_without_server_key(self):
        for provider, (model, url, header, value) in CUSTOM.items():
            with self.subTest(provider), mock.patch.object(advisor, "API_KEY", ""), self.assertLogs(level="DEBUG") as logs:
                self.upstream.clear()
                self.custom_reply = reply(200, ok_body(provider, model))
                res = self.analyze(custom(provider))

                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json, {"analysis": MARKDOWN, "model": model, "provider": provider})
                self.assertEqual(res.headers["Cache-Control"], "no-store")
                self.assertNotIn("Set-Cookie", res.headers)
                [request] = [r for r in self.upstream if r.method == "POST"]
                self.assertEqual((str(request.url), request.headers[header]), (url, value))
                self.assertFalse(any(SECRET in str(r.headers) for r in self.upstream if r.method == "GET"))
                sent = request.content.decode()
                for fact in ["Northeastern University academic advisor", "Corequisites: CS 3001",
                             'Computer Science (BSCS), \\"Four Years, One Co-op\\": Year 2, Spring']:
                    self.assertIn(fact, sent)
                for extra in ['"provider"', '"models"', '"temperature"', SECRET]:
                    self.assertNotIn(extra, sent)
                self.assertNotIn(SECRET, "\n".join(logs.output))
        self.assertEqual(self.sent, [])
        self.assert_clients_closed()

    def test_openai_disables_storage(self):
        self.custom_reply = reply(200, ok_body("openai", "gpt-6-luna"))
        self.analyze(custom("openai"))
        self.assertIs(json.loads(self.upstream[0].content)["store"], False)

    def test_cheapest_thinking_setting_is_tried_first_with_room_to_finish(self):
        cheapest = {
            "openai": {"reasoning": {"effort": "none"}},
            "anthropic": {"thinking": {"type": "disabled"}},
            "gemini": {"thinkingConfig": {"thinkingBudget": 0}},
            "openrouter": {},  # catalog lookup failed (it got a chat reply): model default
        }
        for provider, fields in cheapest.items():
            with self.subTest(provider):
                self.upstream.clear()
                self.custom_reply = reply(200, ok_body(provider, CUSTOM[provider][0]))
                self.assertEqual(self.analyze(custom(provider)).json["analysis"], MARKDOWN)  # thinking text dropped
                [sent] = self.posts()
                config = sent.get("generationConfig", {})
                self.assertEqual({k: v for k, v in {**sent, **config}.items()
                                  if k in ("reasoning", "thinking", "output_config", "thinkingConfig")}, fields)
                self.assertEqual(sent.get("max_output_tokens") or sent.get("max_tokens") or config["maxOutputTokens"], 16000)

    def test_thinking_steps_up_only_on_thinking_rejections_and_remembers_the_model(self):
        def rejecting(count, then):  # reject the first `count` generation requests as thinking errors
            def handler(request):
                if len(self.posts()) <= count:
                    return httpx.Response(400, json={"error": {"type": "invalid_request_error",
                                                               "message": "RAW thinking setting not supported"}})
                return httpx.Response(200, json=then)
            return handler

        ladders = {  # provider: settings tried before the accepted one, as (field, value)
            "openai": [("reasoning", {"effort": "none"}), ("reasoning", {"effort": "minimal"}),
                       ("reasoning", {"effort": "low"})],
            "anthropic": [("thinking", {"type": "disabled"}), ("thinking", {"type": "between_tools"}),
                          ("output_config", {"effort": "low"})],
        }
        for provider, steps in ladders.items():
            with self.subTest(provider):
                self.upstream.clear()
                self.custom_reply = rejecting(2, ok_body(provider, CUSTOM[provider][0]))
                self.assertEqual(self.analyze(custom(provider)).status_code, 200)
                self.assertEqual([(field, sent.get(field)) for sent, (field, _) in zip(self.posts(), steps)], steps)

                self.upstream.clear()  # the accepted rung is remembered for this model
                self.custom_reply = reply(200, ok_body(provider, CUSTOM[provider][0]))
                self.analyze(custom(provider))
                self.assertEqual([(steps[2][0], s.get(steps[2][0])) for s in self.posts()], [steps[2]])

        self.upstream.clear()  # every rung rejected: four attempts, then a safe error
        self.custom_reply = rejecting(99, {})
        res = self.analyze(custom("gemini"))
        self.assertEqual((res.status_code, res.json["code"], len(self.posts())), (400, "thinking_not_supported", 4))
        self.assertNotIn("thinkingConfig", self.posts()[-1]["generationConfig"])  # last try: model default
        self.assertNotIn("RAW", res.get_data(as_text=True))

        self.upstream.clear()  # other 400s are not retried
        self.custom_reply = reply(400, {"error": {"type": "invalid_request_error", "message": "RAW bad prompt"}})
        self.assertEqual(self.analyze(custom("anthropic", model="claude-other")).json["code"], "upstream_error")
        self.assertEqual(len(self.posts()), 1)

    def test_openrouter_uses_catalog_reasoning_metadata(self):
        cases = [
            (None, {}),  # no reasoning support: model default
            ({"mandatory": False, "supported_efforts": ["high", "low", "none"]}, {"reasoning": {"enabled": False}}),
            ({"mandatory": True, "supported_efforts": ["max", "high", "low", "minimal"]}, {"reasoning": {"effort": "minimal"}}),
            ({"mandatory": True, "supported_efforts": ["max", "xhigh", "high", "medium", "low"]}, {"reasoning": {"effort": "low"}}),
            ({"mandatory": True}, {}),  # can't be turned off and no levels: model default
        ]
        for meta, fields in cases:
            with self.subTest(meta=meta):
                self.upstream.clear()
                catalog = {"data": [{"id": "vendor/paid-model", "reasoning": meta}, {"id": "other/model"}]}
                completion_body = ok_body("openrouter", "vendor/paid-model")
                self.custom_reply = lambda r: httpx.Response(200, json=catalog if r.method == "GET" else completion_body)
                self.assertEqual(self.analyze(custom("openrouter")).status_code, 200)
                [sent] = self.posts()
                self.assertEqual({k: v for k, v in sent.items() if k == "reasoning"}, fields)

    def test_invalid_config_never_calls_any_provider(self):
        good = custom("openai")["ai"]
        for ai in [None, [], "custom", {}, {"mode": "other"}, {"mode": "default", "api_key": SECRET},
                   {**good, "provider": "azure"}, {**good, "provider": ["openai"]}, {**good, "api_key": "   "},
                   {**good, "api_key": "sk-has space-123"}, {**good, "api_key": "sk-ctrl\x00123456"},
                   {**good, "model": ""}, {**good, "model": None}, {**good, "model": "text-embedding-3-large"},
                   {**good, "base_url": "https://evil.example"}, {**good, "headers": {"Host": "evil.example"}},
                   {**good, "provider": "gemini", "model": "../../files"},
                   {**good, "provider": "gemini", "model": "gemini-3.5-flash:streamGenerateContent"},
                   {**good, "thinking": True}]:
            with self.subTest(ai=ai):
                res = self.analyze({"dept": "cs", "number": "3000", "ai": ai})
                self.assertEqual((res.status_code, res.json["code"]), (400, "invalid_ai_config"))
                self.assertNotIn(SECRET, res.get_data(as_text=True))
        self.assertEqual((self.upstream, self.sent), ([], []))

        res = self.analyze({"dept": "cs", "number": "3000", "ai": {"mode": "default"}})
        self.assertEqual(res.json, {"analysis": MARKDOWN, "model": "google/gemma-4-31b-it:free"})

    def test_interleaved_keys_stay_isolated_and_default_keeps_server_client(self):
        self.custom_reply = reply(200, ok_body("openai", "gpt-6-luna"))
        keys = ["sk-user-one-111", "sk-user-two-222", "sk-user-one-111"]
        for key in keys:
            self.assertEqual(self.analyze(custom("openai", key=key)).status_code, 200)
        self.assertEqual([r.headers["authorization"] for r in self.upstream], [f"Bearer {k}" for k in keys])

        self.assertEqual(self.analyze().json["model"], "google/gemma-4-31b-it:free")
        self.assertEqual((len(self.upstream), len(self.sent), advisor.API_KEY), (3, 1, "test"))
        self.assert_clients_closed()

    def test_custom_failures_map_to_safe_json(self):
        cases = [
            ("openai", reply(401, {"error": {"code": "invalid_api_key", "message": "RAW"}}), 400, "invalid_api_key"),
            ("gemini", reply(401, {"error": {"code": "authentication", "message": "RAW"}}), 400, "invalid_api_key"),
            ("gemini", reply(400, {"error": {"code": 400, "message": "RAW", "status": "INVALID_ARGUMENT",
                                             "details": [{"reason": "API_KEY_INVALID"}]}}), 400, "invalid_api_key"),
            ("gemini", reply(400, {"error": {"code": 400, "message": "RAW", "status": "INVALID_ARGUMENT"}}), 502, "upstream_error"),
            ("openai", reply(429, {"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted",
                                             "message": "RAW"}}), 402, "insufficient_credits"),
            ("anthropic", reply(400, {"type": "error", "error": {"type": "invalid_request_error",
                                      "message": "RAW: Your credit balance is too low"}}), 402, "insufficient_credits"),
            ("openrouter", reply(402, {"error": {"code": 402, "message": "RAW"}}), 402, "insufficient_credits"),
            ("anthropic", reply(403, {"error": {"type": "permission_error", "message": "RAW"}}), 403, "provider_access_denied"),
            ("anthropic", reply(404, {"error": {"type": "not_found_error", "message": "RAW"}}), 400, "model_not_available"),
            ("openrouter", reply(400, {"error": {"code": 400, "message": "RAW is not a valid model ID"}}), 400, "model_not_available"),
            ("anthropic", reply(429, {"error": {"type": "rate_limit_error"}}, headers={"retry-after": "7"}), 429, "rate_limited"),
            ("anthropic", reply(529, {"error": {"type": "overloaded_error", "message": "RAW"}}), 503, "ai_unavailable"),
            ("openrouter", reply(408, {"error": {"code": 408, "message": "RAW"}}), 504, "ai_timeout"),
            ("gemini", fail(httpx.ReadTimeout("RAW")), 504, "ai_timeout"),
            ("openai", fail(httpx.ConnectError("RAW")), 503, "ai_unavailable"),
            ("openai", reply(200, {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                                   "output": [{"type": "reasoning"}]}), 502, "incomplete_response"),
            ("openai", reply(200, {"status": "completed", "output": [{"type": "message", "content": [
                {"type": "refusal", "refusal": "RAW"}]}]}), 422, "response_blocked"),
            ("openai", reply(200, {"status": "completed", "output": [{"type": "reasoning"}]}), 502, "bad_response"),
            ("anthropic", reply(200, {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "RAW"}]}),
             502, "incomplete_response"),
            ("anthropic", reply(200, {"stop_reason": "refusal", "content": []}), 422, "response_blocked"),
            ("anthropic", reply(200, {"stop_reason": "end_turn", "content": "RAW"}), 502, "bad_response"),
            ("gemini", reply(200, {"promptFeedback": {"blockReason": "SAFETY"}}), 422, "response_blocked"),
            ("gemini", reply(200, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "RAW"}]}}]}),
             502, "incomplete_response"),
            ("gemini", reply(200, {"candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": "RAW", "thought": True}]}}]}), 502, "bad_response"),
            ("gemini", reply(200, {"candidates": []}), 502, "bad_response"),
            ("openrouter", reply(200, {"error": {"code": 402, "message": "RAW"}}), 402, "insufficient_credits"),
            ("openrouter", reply(200, completion("RAW", "length")), 502, "incomplete_response"),
            ("openrouter", lambda request: httpx.Response(200, text="RAW <html>"), 502, "bad_response"),
        ]
        for provider, reply_, status, code in cases:
            with self.subTest(provider=provider, code=code, status=status):
                self.custom_reply = reply_
                res = self.analyze(custom(provider))
                self.assertEqual((res.status_code, res.json["code"]), (status, code))
                text = res.get_data(as_text=True)
                for leak in ["RAW", SECRET, "analysis"]:
                    self.assertNotIn(leak, text)
        self.assertEqual(self.sent, [])
        self.assert_clients_closed()

        self.custom_reply = next(r for p, r, s, c in cases if c == "rate_limited")
        self.assertEqual(self.analyze(custom("anthropic")).json["retry_after_seconds"], 7)

    def models(self, provider, key=SECRET):
        return self.http.post("/api/ai/models", json={"provider": provider, "api_key": key})

    def test_discovery_normalizes_filters_deduplicates_and_paginates(self):
        def page(**body):
            return body

        def gemini(mid, name=None, methods=("generateContent",)):
            return {"name": f"models/{mid}", "displayName": name, "supportedGenerationMethods": list(methods)}

        def router(mid, name, created, inputs=("text",), outputs=("text",)):
            return {"id": mid, "name": name, "created": created,
                    "architecture": {"input_modalities": list(inputs), "output_modalities": list(outputs)}}

        pages = {
            "openai": [page(data=[{"id": "gpt-6-luna", "created": 300}, {"id": "text-embedding-3-large", "created": 900},
                                  {"id": "gpt-realtime-2", "created": 900}, {"id": "o4-mini", "created": 100},
                                  {"id": "gpt-6-luna-2026-09-01", "created": 310}, {"id": "gpt-image-2.5-flare"},
                                  {"id": "gpt-6-luna", "created": 300}, {"id": "babbage-002"}])],
            "anthropic": [page(data=[{"id": "claude-b", "display_name": "Claude B", "created_at": "2026-09-01T00:00:00Z"}],
                               has_more=True, last_id="claude-b"),
                          page(data=[{"id": "claude-a", "display_name": "Claude A", "created_at": "2026-05-01T00:00:00Z"},
                                     {"id": "claude-dep", "display_name": "Claude Dep", "lifecycle": "deprecated",
                                      "created_at": "2026-10-01T00:00:00Z"},
                                     {"id": "claude-old", "display_name": "Old", "lifecycle": "retired"}], has_more=False)],
            "gemini": [page(models=[gemini("gemini-3.5-flash", "Gemini 3.5 Flash", ["generateContent", "countTokens"]),
                                    gemini("gemini-embedding-001", methods=["embedContent"]),
                                    gemini("gemini-2.5-flash-001", "Gemini 2.5 Flash 001")], nextPageToken="t2"),
                       page(models=[gemini("gemini-3.1-flash-image", "Image"), gemini("gemma-3-27b-it"),
                                    gemini("gemini-3.5-pro", "Gemini 3.5 Pro")])],
            "openrouter": [page(data=[router("z/text", "Zed: Text", 500),
                                      router("openai/gpt-6.1-sol", "OpenAI: GPT-6.1 Sol", 400, inputs=["text", "image"]),
                                      router("openai/gpt-6.1-sol:batch", "OpenAI: GPT-6.1 Sol (batch)", 410),
                                      router("anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet 5.5", 300),
                                      router("google/image", "Google: Image", 600, outputs=["image", "text"])])],
        }
        expected = {  # provider: (top ids, newest first; all names A-Z)
            "openai": (["gpt-6-luna", "o4-mini"], ["gpt-6-luna", "gpt-6-luna-2026-09-01", "o4-mini"]),
            "anthropic": (["claude-b", "claude-a"], ["Claude A", "Claude B", "Claude Dep"]),
            "gemini": (["gemini-3.5-pro", "gemini-3.5-flash"], ["Gemini 2.5 Flash 001", "Gemini 3.5 Flash", "Gemini 3.5 Pro"]),
            "openrouter": (["openai/gpt-6.1-sol", "anthropic/claude-sonnet-5.5"],
                           ["Anthropic: Claude Sonnet 5.5", "OpenAI: GPT-6.1 Sol", "OpenAI: GPT-6.1 Sol (batch)", "Zed: Text"]),
        }
        for provider, bodies in pages.items():
            with self.subTest(provider):
                self.upstream.clear()
                self.custom_reply = lambda request: httpx.Response(200, json=bodies.pop(0))
                res = self.models(provider)
                top, names = expected[provider]
                self.assertEqual((res.json["provider"], [m["id"] for m in res.json["top"]]), (provider, top))
                self.assertEqual([m["name"] for m in res.json["models"]], names)
                self.assertEqual(res.headers["Cache-Control"], "no-store")
                self.assertNotIn(SECRET, res.get_data(as_text=True))
                header = self.upstream[0].headers.get(CUSTOM[provider][2], "")
                self.assertEqual(SECRET in header, provider != "openrouter")  # OpenRouter's catalog is public
        self.assert_clients_closed()

    def test_top_is_capped_at_ten_and_openrouter_needs_no_key(self):
        ids = [f"openai/gpt-{letter}" for letter in "abcdefghijkl"]  # oldest first
        data = [{"id": mid, "name": mid, "created": i,
                 "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}} for i, mid in enumerate(ids)]
        self.custom_reply = reply(200, {"data": data})
        res = self.http.post("/api/ai/models", json={"provider": "openrouter"})
        self.assertEqual([m["id"] for m in res.json["top"]], ids[:1:-1])
        self.assertEqual(len(res.json["models"]), 12)
        self.assertNotIn("authorization", self.upstream[0].headers)

    def test_discovery_follows_page_tokens(self):
        for provider, first, param in [("anthropic", {"data": [], "has_more": True, "last_id": "tok"}, "after_id"),
                                       ("gemini", {"models": [], "nextPageToken": "tok"}, "pageToken")]:
            with self.subTest(provider):
                self.upstream.clear()
                bodies = [first, {"data": [], "models": []}]
                self.custom_reply = lambda request: httpx.Response(200, json=bodies.pop(0))
                self.assertEqual(self.models(provider).json["models"], [])
                self.assertEqual(self.upstream[1].url.params[param], "tok")

    def test_discovery_failures_return_safe_json(self):
        for body in [None, {"provider": "openai"}, {"provider": "openai", "api_key": SECRET, "url": "https://evil.example"},
                     {"provider": "azure", "api_key": SECRET}]:
            with self.subTest(body=body):
                res = self.http.post("/api/ai/models", json=body)
                self.assertEqual((res.status_code, res.json["code"]), (400, "invalid_ai_config"))
        self.assertEqual(self.upstream, [])

        endless = {"models": [], "nextPageToken": "again"}
        for reply_, status, code in [
            (reply(401, {"error": {"code": "invalid_api_key", "message": "RAW"}}), 400, "invalid_api_key"),
            (reply(200, endless), 502, "discovery_incomplete"),
            (reply(200, {"models": "RAW"}), 502, "bad_response"),
        ]:
            with self.subTest(code=code):
                self.custom_reply = reply_
                res = self.models("gemini")
                self.assertEqual((res.status_code, res.json["code"]), (status, code))
                self.assertEqual(res.headers["Cache-Control"], "no-store")
                self.assertNotIn("RAW", res.get_data(as_text=True))

        with mock.patch.object(advisor.ai_providers, "list_models", side_effect=RuntimeError(SECRET)):
            res = self.models("openai")
        self.assertEqual((res.status_code, res.json["code"]), (500, "internal_error"))
        self.assertNotIn(SECRET, res.get_data(as_text=True))


class ConfigTest(unittest.TestCase):
    BASE = {"OPENROUTER_MODEL": "google/gemma-4-31b-it:free", "OPENROUTER_FALLBACK_MODELS": "",
            "OPENROUTER_REASONING_ENABLED": "false", "OPENROUTER_MAX_TOKENS": "2048", "OPENROUTER_TIMEOUT_SECONDS": "35"}

    def load(self, **overrides):
        env = {**os.environ, **self.BASE, **overrides}
        return subprocess.run([sys.executable, "-c", "import advisor; print(advisor.FALLBACK_MODELS)"],
                              cwd=os.path.dirname(os.path.abspath(__file__)), env=env, capture_output=True, text=True)

    def test_fallbacks_are_trimmed_deduplicated_and_exclude_primary(self):
        result = self.load(OPENROUTER_FALLBACK_MODELS=" a/b:free , a/b:free,google/gemma-4-31b-it:free,,")
        self.assertEqual(result.stdout.strip(), "['a/b:free']")
        self.assertEqual(self.load().stdout.strip(), "[]")

    def test_invalid_settings_fail_startup(self):
        for key, value in [("OPENROUTER_REASONING_ENABLED", "yes"), ("OPENROUTER_MAX_TOKENS", "0"),
                           ("OPENROUTER_MAX_TOKENS", "lots"), ("OPENROUTER_TIMEOUT_SECONDS", "-1"),
                           ("OPENROUTER_FALLBACK_MODELS", "not a model")]:
            with self.subTest(**{key: value}):
                self.assertNotEqual(self.load(**{key: value}).returncode, 0)


class HistoricalPlansTest(ApiTest):
    def test_api_and_ai_prompt_expose_historical_catalog_year(self):
        dataset = {"catalog_year": "2025-2026", "current_catalog_year": "2026-2027", "plan_count": 622, "historical": True}
        entry = {**PLANS[0], "catalog_year": "2025-2026", "source_url": "https://catalog.northeastern.edu/archive/2025-2026/undergraduate/cs/"}
        with mock.patch.object(advisor, "lookup_plan_dataset", return_value=dataset), mock.patch.object(advisor, "lookup_schedule_context", return_value=[entry]):
            response = self.http.get("/api/course/cs/3000")
            self.assertEqual(response.json["plan_dataset"], dataset)
            self.assertEqual(response.json["schedule_context"][0]["catalog_year"], "2025-2026")
            prompt = advisor.build_prompt(COURSE)
            self.assertIn("These are historical plans; the current catalog is 2026-2027", prompt)
            self.assertIn("sample plan catalog: 2025-2026", prompt)

    def test_ordinal_semesters_do_not_invent_calendar_year(self):
        text = advisor.format_schedule_context([{**PLANS[0], "year": None, "term": "Semester 1", "catalog_year": "2025-2026"}])
        self.assertIn("Semester 1", text)
        self.assertNotIn("Year None", text)


class PlanProvenanceDatabaseTest(unittest.TestCase):
    def test_dataset_provenance_comes_from_loaded_database(self):
        import contextlib
        import sqlite3
        import tempfile
        from pathlib import Path
        import db_loader
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'courses.db'
            with contextlib.closing(sqlite3.connect(path)) as conn:
                db_loader.create_tables(conn.cursor())
                conn.execute('INSERT INTO plan_catalog VALUES (?, ?, ?)', ('2025-2026', '2026-2027', 622))
                conn.commit()
            with mock.patch.object(advisor, 'DB_FILE', str(path)):
                self.assertEqual(advisor.lookup_plan_dataset(), {
                    'catalog_year': '2025-2026', 'current_catalog_year': '2026-2027',
                    'plan_count': 622, 'historical': True,
                })


if __name__ == "__main__":
    unittest.main()
