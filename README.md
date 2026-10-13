# AI Course Advisor

Flask + SQLite API and React frontend for AI breakdowns of Northeastern courses. AI analysis runs on free OpenRouter models.

## Setup

Requires Python 3.10+ and Node 18+.

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set OPENROUTER_API_KEY (server-side only)
cd frontend && npm install
```

If an older `.env` has `GEMINI_API_KEY`, remove it — it is no longer used.

`courses.db` is ignored by git. On a fresh checkout, build it from the checked-in JSON with `python3 db_loader.py`. The loader drops and recreates tables, so don't run it over a database you want to keep; it also doesn't drop `plan_entries`, so a rerun on an existing database fails — delete `courses.db` first.

## Run

With the venv active: `cd frontend && npm start` starts the API (port 8000) and React (port 3000). API only: `python3 advisor.py`.

```sh
curl localhost:8000/api/health
curl -X POST localhost:8000/api/analyze -H 'Content-Type: application/json' -d '{"dept":"cs","number":"3000"}'
```

Without a key, search and course details still work; `/api/analyze` returns 503 `ai_not_configured`. Errors use `{"error": "...", "code": "..."}`.

## Configuration (`.env`)

| Variable | Default | Notes |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Required for analysis |
| `OPENROUTER_MODEL` | `inclusionai/ling-3.1-flash` | Primary, tried first on every request |
| `OPENROUTER_FALLBACK_MODELS` | `nvidia/nemotron-3.5-lightning:free` | Comma-separated; empty disables fallback |
| `OPENROUTER_REASONING_ENABLED` | `false` | `true`/`false`; if `true`, raise max tokens to ~4096 |
| `OPENROUTER_MAX_TOKENS` | `2048` | |
| `OPENROUTER_TIMEOUT_SECONDS` | `35` | SDK network timeout, not a total deadline |

Every request caps price at zero, so a model whose pricing changes fails with 503 `ai_unavailable` instead of costing money.

Free models are typically limited to 20 requests/minute and 50/day (1,000/day after buying credits), account-wide; failed requests may count. Check your limit with `curl -H "Authorization: Bearer $OPENROUTER_API_KEY" https://openrouter.ai/api/v1/key`. Rate limits surface as 429 `rate_limited`. NVIDIA free endpoints log prompts, so don't send personal data.

To revalidate models, confirm each ID still lists zero prompt/completion pricing and supports `reasoning`, `temperature`, `max_tokens`:

```sh
curl -s https://openrouter.ai/api/v1/models/inclusionai/ling-3.1-flash/endpoints
```

## Tests

```sh
python3 -m unittest -v                              # backend, offline, no key or DB needed
cd frontend && CI=true npm test && npm run build
```
