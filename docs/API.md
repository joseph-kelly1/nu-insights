# API reference

The hosted API is available at `https://nuinsights.josephkelly.dev/api`, on the same origin as the frontend. Check [server health](https://nuinsights.josephkelly.dev/api/health) for status and default AI configuration. Locally, the React development server proxies `/api` to `http://localhost:8000`. POST responses use `Cache-Control: no-store`. Errors generally return `{"error": "...", "code": "..."}`; exam-policy validation errors currently return an `error` message without a code.

<details>
<summary><b>Endpoints and request options</b></summary>

| Endpoint | Purpose |
| --- | --- |
| `GET /api/search?q=` | Search by code/title. Optional `catalog_year` selects archived course data. |
| `GET /api/course/<dept>/<number>` | Course details and companion courses. Optional `catalog_year` selects a historical record. |
| `GET /api/programs` | Program IDs, labels, campus/degree metadata, and sample-plan availability. |
| `GET /api/programs/<id>/courses?q=&offset=` | Current requirement courses, 20 per page. `view=sections` returns unpaginated sections with preserved alternatives; `concentrations=<id>,<id>` selects concentration blocks. |
| `GET /api/programs/<id>/concentrations` | Concentration options and selection policy. Optional `catalog_year` selects an archived edition. |
| `GET /api/programs/<id>/planning-context?catalog_year=` | Planner capability, requirements, sources, sample plans, and replacement summaries. Optional comma-separated `concentrations` selects options. |
| `POST /api/planner/validate` | Check `{"plan": {...}}` against its selected catalog. Optional `dataset` rejects stale data. |
| `POST /api/planner/generate` | Send `{"plan": {...}, "mode": "ai"}` or `"mode": "deterministic"`. Returns a checked proposal/diff and ranking outcome. Optional `dataset` and `ai` configuration. |
| `POST /api/planner/identify` | Send `program_id`, `phrases` (1–15 course names), optional `term`, and optional `ai` configuration. Returns candidate matches for review. |
| `POST /api/analyze` | Send `dept`, `number`, optional `major`, optional `concentrations`, and optional `ai` configuration for a course explanation. |
| `POST /api/ai/models` | Send `provider` and `api_key` for model discovery. OpenRouter needs only `provider`. |
| `GET /api/exams/catalog` | Exam subjects and published policy snapshots. Optional `policy_year` and `version`. |
| `POST /api/exams/resolve` | Send `{"exams": [...]}` to validate scores/levels and resolve equivalent course awards. |
| `GET /api/health` | Server status, default model, and whether default AI is configured. |

Custom AI configuration for supported POST routes:

```json
{
  "ai": {
    "mode": "custom",
    "provider": "openai",
    "api_key": "your-key",
    "model": "your-model-id"
  }
}
```

Providers are `openai`, `anthropic`, `gemini`, and `openrouter`. Omit `ai` to use the default route. Plan exports from the UI provide the plan structure; custom keys are never part of those exports.

</details>
