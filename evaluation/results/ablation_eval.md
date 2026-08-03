# Tier-3 retrieval ablation

Headline result (PROJECT_PLAN.md Section 7.5): the 10 Tier-3 golden questions — business-phrased questions that only map to a correct query via a defined metric in `semantic_layer/metrics.yml` — run with retrieval disabled (raw schema dump only, no metric definitions) vs enabled (the real `search_schema` pipeline: rewrite -> hybrid search -> rerank). Execution accuracy against the golden reference result, same methodology as `evaluation/results/llm_eval.md`. Two models, so the effect isn't specific to one.

| Model | Condition | Execution accuracy |
|---|---|---|
| llama3 | retrieval disabled | 0.300 |
| llama3 | retrieval enabled | 0.800 |
| gpt-4o-mini | retrieval disabled | 0.500 |
| gpt-4o-mini | retrieval enabled | 1.000 |

## Methodology note

A first run of this script used the default 30s Ollama timeout and saw 6 of 20 `llama3` calls fail with a connection timeout (not a real model failure), concentrated right after the reranker's cross-encoder model was lazily loaded — CPU contention between local inference and Ollama generation in the same process. Diagnosed rather than reported as-is: the `llama3` timeout was raised to 90s for this script only (see `llama3_chat_fn` in `run_ablation.py`; the production default in `src/llm_client.py` is unaffected). The run below is the re-measurement at 90s.

## Corroboration against Day 11

Day 11's LLM evaluation (`evaluation/results/llm_eval.md`) already measured baseline vs schema-grounded accuracy on these same 10 questions as part of its by-tier breakdown, from an independent run (unfixed API temperature, so not expected to match exactly — see the variance note in `evaluation/results/self_correction_eval.md`). Comparison:

| Model | Condition | This run | Day 11 |
|---|---|---|---|
| llama3 | retrieval disabled | 0.300 | 0.100 |
| llama3 | retrieval enabled | 0.800 | 0.700 |
| gpt-4o-mini | retrieval disabled | 0.500 | 0.400 |
| gpt-4o-mini | retrieval enabled | 1.000 | 1.000 |

## Cost

Total OpenAI (`gpt-4o-mini`) tokens across this ablation: 15,251 (prompt + completion, from real API usage figures, not estimated). Local Ollama has no billable usage.

Full per-question outcomes (generated SQL, correctness, errors) are in `ablation_outcomes.json`, alongside this report.
