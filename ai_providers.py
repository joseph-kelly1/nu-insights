"""Bring-your-own-key AI providers: config validation, model discovery, and generation.

Every call opens a fresh HTTP client with the user's key and closes it afterwards, so keys
never reach module state, the environment, or the server's default OpenRouter client.
Endpoints are fixed here: users pick a provider ID, never a URL or header.
"""

import json
import re
import time

import httpx2 as httpx

# Custom-mode limits, separate from the OPENROUTER_* settings of the free default mode.
# Many current models think before answering on their own, so both limits leave room for that:
# a cut-off answer still bills the user for every token. No automatic retries.
TIMEOUT_SECONDS = 120  # httpx per-operation network timeout in seconds, not a total deadline
MAX_TOKENS = 16000     # output cap including thinking tokens; a ceiling, not a spend
MAX_PAGES = 5          # discovery pagination bound
LIST_TIMEOUT_SECONDS = 15  # model lists answer fast; don't let a hung one stall the UI or an analysis

# Thinking: always the cheapest setting a model accepts. Each list runs cheapest first and ends with
# the model default ({}); the next rung is tried only when the provider rejects the current one with a
# 400 about that parameter (rejected requests aren't billed). Reviewed 2026-10-13:
# OpenAI effort none/minimal/low (https://developers.openai.com/api/docs/guides/reasoning); Claude
# disabled, then between_tools (Sonnet 5.5's off switch), then effort low for models that always think
# (https://platform.claude.com/docs/en/build-with-claude/extended-thinking); Gemini budget 0 (2.5), then
# thinkingLevel minimal/low (3.x) (https://ai.google.dev/gemini-api/docs/thinking).
# OpenRouter publishes per-model reasoning metadata instead; see _openrouter_reasoning.
THINKING_RUNGS = {
    "openai": [{"reasoning": {"effort": e}} for e in ("none", "minimal", "low")] + [{}],
    "anthropic": [{"thinking": {"type": "disabled"}}, {"thinking": {"type": "between_tools"}},
                  {"output_config": {"effort": "low"}}, {}],
    "gemini": [{"thinkingConfig": {"thinkingBudget": 0}}, {"thinkingConfig": {"thinkingLevel": "minimal"}},
               {"thinkingConfig": {"thinkingLevel": "low"}}, {}],
}
EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]  # cheapest first
# ponytail: in-process memo of the rung each model accepted, so the ladder runs once per model per
# restart. Keyed by provider and model only, never by key.
_cheapest_rung: dict[tuple[str, str], int] = {}

PROVIDERS = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini", "openrouter": "OpenRouter"}
OPENAI = "https://api.openai.com/v1"
ANTHROPIC = "https://api.anthropic.com/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
OPENROUTER = "https://openrouter.ai/api/v1"

# Capability rules, reviewed 2026-10-12. These describe families, not a frozen catalog: live
# discovery decides what exists, and unlisted IDs stay enterable manually without a guarantee.
# OpenAI (https://developers.openai.com/api/docs/models): Responses text models are the gpt-N,
#   o-series and chatgpt families; /v1/models also lists embeddings, audio, image, moderation, etc.
# Gemini (https://ai.google.dev/api/models): generateContent support alone doesn't mean text output.
#   Gemma rejects native system instructions.
OPENAI_TEXT = re.compile(r"gpt-[4-9]|o\d|chatgpt-")
# "Top 10" = newest releases. No provider API publishes popularity, so this is the closest live signal.
# Dated snapshots (...-2026-09-01, ...-001, ...-20251101) and variants (...:free, ...:batch) stay out of it,
# and on OpenRouter only major labs count, so a flood of small new models doesn't crowd the top.
NOT_TOP = re.compile(r"-\d{2,}$|:")
MAJOR_LABS = {"openai", "anthropic", "google", "meta", "meta-llama", "mistralai", "x-ai", "deepseek", "qwen"}
INCOMPATIBLE = {
    "openai": re.compile(r"embed|tts|whisper|transcribe|dall-e|image|moderation|realtime|live|audio|search"
                         r"|research|codex|computer-use|cyber"),
    "gemini": re.compile(r"embed|tts|transcribe|image|imagen|veo|lyria|omni|live|audio|aqa|robotics"
                         r"|research|computer-use|antigravity|gemma"),
}


class AIError(Exception):
    """AI failure with a safe HTTP status and JSON error envelope for the browser."""

    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(code)
        self.status = status
        self.body = {"error": message, "code": code}
        if retry_after:
            self.body["retry_after_seconds"] = retry_after


# --- Validation ---

def _invalid(message: str) -> AIError:
    return AIError(400, "invalid_ai_config", message)


def _model_ok(provider: str, model) -> bool:
    # Gemini IDs go into the URL path, so they may not contain "/" or ":".
    pattern = r"[\w.-]{1,200}" if provider == "gemini" else r"[\w.:/@-]{1,200}"
    incompatible = INCOMPATIBLE.get(provider)
    return (isinstance(model, str) and bool(re.fullmatch(pattern, model))
            and not (incompatible and incompatible.search(model.lower())))


def parse_credentials(raw, *extra_fields) -> tuple[str, str]:
    """Validate exactly {provider, api_key, *extra_fields}. Unknown fields (URLs, headers) are rejected."""
    if not (isinstance(raw, dict) and raw.keys() == {"provider", "api_key", *extra_fields}):
        raise _invalid("Send the AI provider and API key only.")
    provider, key = raw["provider"], raw["api_key"]
    if not (isinstance(provider, str) and provider in PROVIDERS):
        raise _invalid("Choose a supported AI provider.")
    key = key.strip() if isinstance(key, str) else ""
    if not re.fullmatch(r"[\x21-\x7e]{8,512}", key):  # printable ASCII: no spaces or control characters
        raise _invalid("Enter a valid API key in AI settings.")
    return provider, key


def parse_ai_config(raw) -> tuple[str, str, str] | None:
    """Return None for app-default routing or (provider, api_key, model) for a user key.
    Anything malformed is an error; it never falls back to the default."""
    if raw == {"mode": "default"}:
        return None
    if not (isinstance(raw, dict) and raw.get("mode") == "custom"):
        raise _invalid('Send "ai" as {"mode": "default"} or a complete custom configuration.')
    provider, key = parse_credentials(raw, "mode", "model")
    model = raw["model"].strip() if isinstance(raw["model"], str) else ""
    if provider == "gemini":
        model = model.removeprefix("models/")
    if not _model_ok(provider, model):
        raise _invalid("Choose a supported model or enter a valid model ID.")
    return provider, key, model


def parse_discovery(raw) -> tuple[str, str | None]:
    """Validate a model-list request. OpenRouter's catalog is public, so it needs no key."""
    if raw == {"provider": "openrouter"}:
        return "openrouter", None
    return parse_credentials(raw)


# --- HTTP and error mapping ---

def _provider_error(provider: str, status, body, retry_after: str = "") -> AIError:
    """Map a provider HTTP status or embedded error to a safe AIError. Raw messages are never returned."""
    name = PROVIDERS[provider]
    error = body.get("error") if isinstance(body, dict) else None
    detail = json.dumps(error).lower() if error else ""  # searched for documented codes only
    if status == 401 or "api_key_invalid" in detail:  # Gemini has reported bad keys as 400 API_KEY_INVALID
        return AIError(400, "invalid_api_key", f"{name} rejected your API key. Check it in AI settings.")
    if status == 402 or any(m in detail for m in ("insufficient_quota", "credit_balance", "credit balance")):
        return AIError(402, "insufficient_credits", f"Your {name} account is out of credits or has a billing problem.")
    if status == 404 or "model_not_found" in detail or "not a valid model" in detail:
        return AIError(400, "model_not_available", f"{name} can't run that model with your key. Choose another model.")
    if status == 400 and any(word in detail for word in ("reasoning", "thinking", "effort", "budget")):
        return AIError(400, "thinking_not_supported", f"{name} rejected this model's thinking settings. Choose another model.")
    if status == 403:
        return AIError(403, "provider_access_denied", f"{name} denied this key access to the request or model.")
    if status == 429:
        return AIError(429, "rate_limited", f"{name} is rate-limiting your key. Try again shortly.",
                       int(retry_after) if retry_after.isdigit() else None)
    if status in (408, 504):
        return AIError(504, "ai_timeout", f"{name} took too long to respond. Try again.")
    if isinstance(status, int) and status >= 500:
        return AIError(503, "ai_unavailable", f"{name} is unavailable right now. Try again later.")
    return AIError(502, "upstream_error", f"{name} returned an error. Check your model choice and try again.")


def _request(provider: str, method: str, url: str, headers: dict, timeout=TIMEOUT_SECONDS, **kwargs) -> dict:
    name = PROVIDERS[provider]
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.request(method, url, headers=headers, **kwargs)
    except httpx.TimeoutException:
        raise AIError(504, "ai_timeout", f"{name} took too long to respond. Try again.")
    except httpx.HTTPError:
        raise AIError(503, "ai_unavailable", f"Could not reach {name}. Try again later.")
    try:
        body = res.json()
    except ValueError:
        body = None
    if not res.is_success:
        raise _provider_error(provider, res.status_code, body, res.headers.get("retry-after", ""))
    if not isinstance(body, dict):
        raise _bad(provider)
    return body


def _bad(provider: str) -> AIError:
    return AIError(502, "bad_response", f"{PROVIDERS[provider]} returned an unusable response. Try again.")


def _cut_off(provider: str) -> AIError:
    return AIError(502, "incomplete_response",
                   f"The {PROVIDERS[provider]} response was cut off before it finished. Try again or choose another model.")


def _blocked(provider: str) -> AIError:
    return AIError(422, "response_blocked", f"{PROVIDERS[provider]} declined to answer this request.")


# --- Discovery ---

def _pages(provider: str, url: str, headers: dict, items: str, next_params, params=None) -> list:
    found = []
    for _ in range(MAX_PAGES):
        body = _request(provider, "GET", url, headers, LIST_TIMEOUT_SECONDS, params=params)
        found += body[items]
        if not (params := next_params(body)):
            return found
    raise AIError(502, "discovery_incomplete", f"{PROVIDERS[provider]} returned too many models to list. Enter a model ID.")


# Each lister returns (id, display name, newness, top-eligible); higher newness = newer.
# OpenRouter models must output text only: image, audio, and music generators are skipped.

def _openai_models(key):
    data = _pages("openai", f"{OPENAI}/models", {"Authorization": f"Bearer {key}"}, "data", lambda b: None)
    return [(m["id"], m["id"], m.get("created") or 0, True) for m in data if OPENAI_TEXT.match(m["id"])]


def _anthropic_models(key):
    data = _pages("anthropic", f"{ANTHROPIC}/models", {"x-api-key": key, "anthropic-version": "2023-06-01"}, "data",
                  lambda b: b.get("has_more") and {"limit": 1000, "after_id": b["last_id"]}, {"limit": 1000})
    return [(m["id"], m.get("display_name"), m.get("created_at") or "", m.get("lifecycle") != "deprecated")
            for m in data if m.get("lifecycle") != "retired"]


def _gemini_newness(model_id: str) -> tuple:
    # Gemini lists no release dates: higher version first, then shorter IDs (aliases before variants).
    version = re.match(r"gemini-(\d+(?:\.\d+)?)", model_id)
    return float(version[1]) if version else 0.0, -len(model_id)


def _gemini_models(key):
    data = _pages("gemini", f"{GEMINI}/models", {"x-goog-api-key": key}, "models",
                  lambda b: b.get("nextPageToken") and {"pageSize": 1000, "pageToken": b["nextPageToken"]},
                  {"pageSize": 1000})
    ids = [(m["name"].removeprefix("models/"), m.get("displayName")) for m in data
           if "generateContent" in m.get("supportedGenerationMethods", [])]
    return [(mid, name, _gemini_newness(mid), True) for mid, name in ids]


def _openrouter_catalog() -> list:
    # The catalog is public, so the user's key (if any) isn't sent.
    return _pages("openrouter", f"{OPENROUTER}/models", {}, "data", lambda b: None)


def _openrouter_models(key):
    data = _openrouter_catalog()
    return [(m["id"], m.get("name"), m.get("created") or 0, m["id"].split("/")[0] in MAJOR_LABS) for m in data
            if "text" in m["architecture"]["input_modalities"] and m["architecture"]["output_modalities"] == ["text"]]


def list_models(provider: str, api_key: str | None) -> dict:
    """Live catalog: the 10 newest flagship models, then every usable model A-Z.
    Listing does not verify access or billing."""
    try:
        found = {mid: (str(name or mid), newness, top_ok)
                 for mid, name, newness, top_ok in _LISTERS[provider](api_key) if _model_ok(provider, mid)}
        newest = sorted((mid for mid, (_, _, top_ok) in found.items() if top_ok and not NOT_TOP.search(mid)),
                        key=lambda mid: found[mid][1], reverse=True)
    except (AttributeError, KeyError, TypeError):
        raise AIError(502, "bad_response", f"{PROVIDERS[provider]} returned an unusable model list.")

    def entry(mid):
        return {"id": mid, "name": found[mid][0]}
    return {"top": [entry(mid) for mid in newest[:10]],
            "models": sorted(map(entry, found), key=lambda m: m["name"].lower())}


# --- Generation: each returns (text, upstream model, response id, usage) ---
# `thinking` holds the request fields for one THINKING_RUNGS setting. Thinking text is never returned.

def _openai(key, model, system, prompt, thinking):
    body = _request("openai", "POST", f"{OPENAI}/responses", {"Authorization": f"Bearer {key}"}, json={
        "model": model, "instructions": system, "input": prompt, "max_output_tokens": MAX_TOKENS, "store": False,
        **thinking})
    if body.get("status") == "incomplete":
        reason = (body.get("incomplete_details") or {}).get("reason")
        raise _blocked("openai") if reason == "content_filter" else _cut_off("openai")
    content = [c for item in body["output"] if item["type"] == "message" for c in item["content"]]
    if any(c["type"] == "refusal" for c in content):
        raise _blocked("openai")
    text = "".join(c["text"] for c in content if c["type"] == "output_text").strip()
    if body.get("status") != "completed" or not text:
        raise _bad("openai")
    return text, body.get("model"), body.get("id"), body.get("usage")


def _anthropic(key, model, system, prompt, thinking):
    body = _request("anthropic", "POST", f"{ANTHROPIC}/messages",
                    {"x-api-key": key, "anthropic-version": "2023-06-01"}, json={
        "model": model, "max_tokens": MAX_TOKENS, "system": system,
        "messages": [{"role": "user", "content": prompt}], **thinking})
    stop = body.get("stop_reason")
    if stop == "refusal":
        raise _blocked("anthropic")
    if stop in ("max_tokens", "model_context_window_exceeded"):
        raise _cut_off("anthropic")
    text = "".join(b["text"] for b in body["content"] if b["type"] == "text").strip()
    if stop not in ("end_turn", "stop_sequence") or not text:
        raise _bad("anthropic")
    return text, body.get("model"), body.get("id"), body.get("usage")


def _gemini(key, model, system, prompt, thinking):
    # model passed _model_ok, so it is safe to place in the path.
    body = _request("gemini", "POST", f"{GEMINI}/models/{model}:generateContent", {"x-goog-api-key": key}, json={
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": MAX_TOKENS, "responseMimeType": "text/plain", **thinking}})
    candidate = (body.get("candidates") or [{}])[0]
    finish = candidate.get("finishReason")
    if (body.get("promptFeedback") or {}).get("blockReason") or finish in (
            "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
        raise _blocked("gemini")
    if finish == "MAX_TOKENS":
        raise _cut_off("gemini")
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()  # never return thinking
    if finish != "STOP" or not text:
        raise _bad("gemini")
    return text, body.get("modelVersion"), body.get("responseId"), body.get("usageMetadata")


def _openrouter_reasoning(model: str) -> dict:
    """Cheapest reasoning setting from OpenRouter's catalog: off if optional, else the lowest
    supported effort, else the model default. A catalog failure only costs the optimization."""
    try:
        meta = next((m.get("reasoning") for m in _openrouter_catalog() if m.get("id") == model), None)
        if not isinstance(meta, dict):
            return {}
        if not meta.get("mandatory"):
            return {"reasoning": {"enabled": False}}
        efforts = [e for e in EFFORTS if e in (meta.get("supported_efforts") or [])]
        return {"reasoning": {"effort": efforts[0]}} if efforts else {}
    except (AIError, AttributeError, KeyError, TypeError):
        return {}


def _openrouter(key, model, system, prompt, thinking):
    # No free-only price caps or fallback models: exactly the user's model and key.
    body = _request("openrouter", "POST", f"{OPENROUTER}/chat/completions", {"Authorization": f"Bearer {key}"}, json={
        "model": model, "max_tokens": MAX_TOKENS,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], **thinking})
    choice = (body.get("choices") or [{}])[0]
    error = body.get("error") or choice.get("error")  # OpenRouter can embed errors in HTTP 200 bodies
    if error:
        raise _provider_error("openrouter", error.get("code") if isinstance(error, dict) else None, {"error": error})
    finish = choice.get("finish_reason")
    if finish == "length":
        raise _cut_off("openrouter")
    if finish == "content_filter":
        raise _blocked("openrouter")
    text = ((choice.get("message") or {}).get("content") or "").strip()
    if finish != "stop" or not text:
        raise _bad("openrouter")
    return text, body.get("model"), body.get("id"), body.get("usage")


def generate(provider: str, api_key: str, model: str, system: str, prompt: str) -> dict:
    """One completion with the user's key and model, at the cheapest thinking setting it accepts.
    No fallback model or server key; the only repeats are after free 400 rejections of a thinking rung."""
    started = time.monotonic()
    rungs = [_openrouter_reasoning(model)] if provider == "openrouter" else THINKING_RUNGS[provider]
    rung = _cheapest_rung.get((provider, model), 0)
    while True:
        try:
            text, upstream_model, response_id, usage = _GENERATORS[provider](api_key, model, system, prompt, rungs[rung])
            break
        except AIError as e:
            if e.body["code"] != "thinking_not_supported" or rung + 1 == len(rungs):
                raise
            rung += 1
        except (AttributeError, KeyError, TypeError):  # malformed response shapes
            raise _bad(provider)
    _cheapest_rung[(provider, model)] = rung
    return {
        "analysis": text,
        "model": upstream_model if isinstance(upstream_model, str) and upstream_model else model,
        "provider": provider,
        "id": response_id if isinstance(response_id, str) else None,
        "usage": {k: v for k, v in usage.items() if isinstance(v, (int, float))} if isinstance(usage, dict) else None,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


_LISTERS = {"openai": _openai_models, "anthropic": _anthropic_models, "gemini": _gemini_models,
            "openrouter": _openrouter_models}
_GENERATORS = {"openai": _openai, "anthropic": _anthropic, "gemini": _gemini, "openrouter": _openrouter}
