# Self-correction lift

Measures whether the validate-and-retry loop (up to 2 attempts, `src/agent/loop.py`) improves execution accuracy over a single-shot attempt, against all 50 golden questions, using the Day 11 production winner: OpenAI `gpt-4o-mini` with schema-grounded context. Each question is run once through the full loop; single-shot accuracy is read from the first attempt's result, and retry-enabled accuracy from the loop's final result — an apples-to-apples comparison, since both arms share the same first attempt rather than being sampled independently.

| Condition | Execution accuracy |
|---|---|
| Single-shot (no retry) | 0.840 |
| Retry-enabled (max 2 attempts) | 0.860 |

Accuracy delta from enabling retry: **+0.020**

## By tier

| Tier | Single-shot | Retry-enabled |
|---|---|---|
| 1 | 0.950 | 0.950 |
| 2 | 0.650 | 0.700 |
| 3 | 1.000 | 1.000 |

## Retry behaviour

Retry was triggered (attempt 1 judged implausible by `validate_result`) on 4 of 50 questions.
- Rescued (wrong on attempt 1, correct after retry): 1
- Regressed (correct on attempt 1, wrong after retry): 0

`validate_result` is a heuristic plausibility check (empty/NULL results, out-of-range rate values), not a correctness oracle against the golden reference — so retry only ever fires when that heuristic happens to catch a problem. An attempt that is confidently wrong in a way the heuristic can't detect (e.g. a plausible-looking but incorrect join) never gets a second try, which bounds how much lift this loop can produce by construction, not by chance.

## Cost

Total OpenAI (`gpt-4o-mini`) tokens across this evaluation: 64,406 (prompt + completion, from real API usage figures, not estimated).

## Note on variance vs the Day 11 LLM evaluation

Single-shot accuracy here (0.840) differs slightly from Day 11's independently-measured `gpt-4o-mini`/schema-grounded execution accuracy (0.880, `evaluation/results/llm_eval.md`) on the same 50 questions. This is expected run-to-run sampling variance, not a data inconsistency: `chat_openai_compatible` (`src/llm_client.py`) does not pin a temperature, so the two measurements are two independent samples of a non-deterministic model rather than a repeat of the same calls. The retry-lift comparison above is internally consistent regardless, since single-shot and retry-enabled accuracy are read from the same run's same first attempts.
