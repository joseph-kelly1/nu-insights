# AI settings and privacy

Open **Model settings**, then **Use my API key**, choose a provider, enter a key, and select a model. Discovery shows the 10 newest eligible flagship models first, then the full supported list. OpenRouter's public model list loads without a key. Listing a model does not verify your account's access or billing.

Keys stay in page memory and travel through this app's backend to the selected provider. They are not stored, logged, exported, or replaced with the server's key. Reloading clears the key; non-secret provider/model preferences can persist. Custom requests are billed to your provider account.

The default route enforces $0 price limits. Custom requests ask for the cheapest thinking setting supported by the model. Ranking requests send interests and candidate course details; course explanations send the selected course and relevant major/concentration context.

<details>
<summary><b>Default AI configuration</b></summary>

For local development, set these in the root `.env` file. For the hosted app, configure them in the Railway service's environment variables; never put keys in the frontend build.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | none | Enables the free default AI mode |
| `OPENROUTER_MODEL` | `google/gemma-4-31b-it:free` | Primary model |
| `OPENROUTER_FALLBACK_MODELS` | `openrouter/free` | Comma-separated default routing fallbacks; empty disables them |
| `OPENROUTER_REASONING_ENABLED` | `false` | Whether default requests enable reasoning |
| `OPENROUTER_MAX_TOKENS` | `2048` | Default output-token cap |
| `OPENROUTER_TIMEOUT_SECONDS` | `35` | SDK network timeout, not a total request deadline |

Custom-provider requests use separate limits in `ai_providers.py`: 16,000 output tokens, a 120-second network timeout, and 15 seconds for model discovery. Provider rate limits depend on the selected account and model.

</details>

## Provider errors

The server checks AI course codes against the catalog and uses structured output when supported. Invalid, incomplete, refused, rate-limited, or timed-out elective rankings do not stop plan generation. Billing, credential, and access errors are shown to the user. A custom request keeps its selected provider, model, and key. The app does not retry a completed malformed ranking. It may retry after a provider rejects a thinking parameter.
