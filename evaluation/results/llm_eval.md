# LLM evaluation

Evaluated against all 50 golden questions. Execution accuracy: generated SQL is run under the production guardrails and compared to the golden reference result as an order-insensitive row set. A guardrail violation, execution/API error, or mismatched result all count as incorrect. Models: local Ollama `llama3` (free) and OpenAI `gpt-4o-mini` (paid). Prompts: baseline (raw schema dump only) vs schema-grounded (retrieved semantic layer context, via the same search_schema pipeline the production agent uses).

| Model | Prompt | Execution accuracy |
|---|---|---|
| llama3 | baseline | 0.340 |
| llama3 | schema-grounded | 0.600 |
| gpt-4o-mini | baseline | 0.620 |
| gpt-4o-mini | schema-grounded | 0.880 |

Best approach used in production: **gpt-4o-mini / schema-grounded**

## Methodology notes

The free-tier model was originally Groq's hosted `llama-3.3-70b-versatile`. Mid-evaluation, Groq's free-tier daily token quota (100K/day) was exhausted by repeated runs during development, which silently mis-scored 31 of 50 questions as wrong in one run (a missing print statement on the API-error path masked that every one of those was actually an HTTP 429 rate-limit response, not a real model failure — fixed, and covered by tests/test_run_llm_eval.py's retry tests). Rather than keep fighting an external quota, the free-tier arm was switched to local Ollama `llama3`, which has no external rate limit to exhaust and matches PROJECT_PLAN.md Section 5.5's framing directly ("Development: Groq free tier and/or local Ollama... Final evaluation runs: one small paid model"). The numbers above are the clean post-switch measurement.

1 of 200 calls in this run hit a transient API/connection error (`llama3`/schema-grounded, question t3_08) and was counted as incorrect per the methodology above, not excluded or retried indefinitely — negligible at this scale, disclosed for completeness.

## By tier

| Model | Prompt | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| llama3 | baseline | 0.700 | 0.100 | 0.100 |
| llama3 | schema-grounded | 0.900 | 0.250 | 0.700 |
| gpt-4o-mini | baseline | 0.750 | 0.600 | 0.400 |
| gpt-4o-mini | schema-grounded | 1.000 | 0.700 | 1.000 |

## Cost

Total OpenAI (`gpt-4o-mini`) tokens across both prompt runs: 78,597 (prompt + completion, from real API usage figures, not estimated). Local Ollama has no billable usage.
