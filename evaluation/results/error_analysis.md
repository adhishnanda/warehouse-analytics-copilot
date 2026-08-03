# Error analysis

Grounded in two real evidence files, not inferred after the fact:

- `ablation_outcomes.json` — full generated SQL for all 40 calls in the
  Tier-3 retrieval ablation (`evaluation/results/ablation_eval.md`).
- `error_analysis_traces.json` — full per-attempt SQL, errors, and
  `validate_result` reasoning for the 7 questions that failed in Day
  12's self-correction evaluation (`evaluation/results/
  self_correction_eval.md`), re-run through the production agent loop
  (`gpt-4o-mini` + schema-grounded context) with full logging
  (`evaluation/run_error_analysis.py`).

Every example below is a real generated query, not a hypothetical.

## Category A: grain mistakes — the clearest evidence for why the semantic layer matters

`fact_orders` is at line-item grain, not order grain — `fact_orders.yml`
carries an explicit caveat about this ("Counting rows answers 'how many
order lines', not 'how many orders' — use COUNT(DISTINCT order_key)"),
and `metrics.yml` defines `average_order_value` and
`repeat_customer_rate` correctly accounting for it. Without retrieval
(the ablation's "retrieval disabled" arm), `gpt-4o-mini` reinvents these
metrics from scratch and gets the grain wrong every time it was sampled:

- **t3_04/t3_05/t3_06** ("average order value", asked three different
  ways): all three generated `SELECT AVG(net_revenue) AS ... FROM
  fact_orders` — averaging over *line items*, not orders. This computes
  average revenue per line, not per order. TPC-H orders average ~4
  lines each (600,572 lines / 150,000 orders), so this systematically
  understates the true average order value by roughly that factor. The
  correct formula
  (`SUM(net_revenue) * 1.0 / COUNT(DISTINCT order_key)`) is exactly
  what `metrics.yml`'s `average_order_value` defines.
- **t3_02** ("what share of our customers have ordered more than
  once"): generated `COUNT(order_key)` (not `COUNT(DISTINCT
  order_key)`) per customer to determine repeat-purchase status —
  inflates the order count for any customer with a multi-line order,
  misclassifying single-order customers as repeat customers. This is
  the precise mistake `fact_orders.yml`'s grain caveat exists to
  prevent.

With retrieval enabled, `gpt-4o-mini` scored 1.000 on all 10 Tier-3
questions (`ablation_eval.md`) — these grain mistakes did not recur.
This is the concrete mechanism behind the ablation's headline number,
not just a correlation.

## Category B: wrong dimension chosen despite retrieval being enabled

**t2_01** ("What is total revenue by region?"), rerun with retrieval
enabled, grouped by `dim_customer.market_segment` instead of any
region/nation column:

```sql
SELECT dc.market_segment, SUM(fo.net_revenue) AS total_revenue
FROM fact_orders fo
JOIN dim_customer dc ON fo.customer_key = dc.customer_key
GROUP BY dc.market_segment
```

`validate_result` marked this plausible (five non-null revenue rows) —
the heuristic has no way to know the grouping dimension is wrong, only
whether the shape of the result looks sane. This is a genuine retrieval
*ranking* problem, not a missing-context problem: `market_segment` is a
real, documented column, just not the one the question asked for. It
suggests the retrieved context per question may need to more strongly
distinguish the requested dimension from other plausible-looking
groupable columns on the same table.

## Category C: descriptive name vs. key column — a scoring-methodology caveat as much as a model one

**t2_02** ("total revenue by supplier nation") grouped by
`ds.nation_key` (an integer, e.g. `0`, `1`, `18`) rather than
`ds.nation_name`. Manually checking the two result sets shows the
*revenue figures line up exactly* with the golden reference once
nation keys are mapped to names — the join and aggregation are
correct, only the label column differs. The order-insensitive,
exact-value `results_match` comparison (used identically in Day 11,
Day 12, and the ablation, for methodology consistency) scores this as
entirely wrong, the same as a logically incorrect query. This is worth
disclosing as a real limitation of the evaluation methodology, not only
of the model: execution-accuracy-by-exact-match cannot distinguish "the
underlying logic is right but the label column is wrong" from "the
underlying logic is wrong."

## Category D: stored-value casing mismatch produces a silent false answer

**t2_11** ("order lines fulfilled by suppliers based in Asia"), retry
attempt: `WHERE ... region_name = 'Asia'`. The data (per
`dim_region.yml`'s own examples, e.g. `"EUROPE"`, `"ASIA"`) is stored
upper-case; the model guessed title case. The query is syntactically
and logically correct — it simply matches zero rows, and DuckDB has no
error to raise. `validate_result` passed it (a count of 0 is a valid
non-null, non-empty single-row result; the heuristic has no
"suspiciously exactly zero" check). This is a real gap: a
value-casing mismatch degrades silently into a wrong-but-confident
answer rather than a retriable error, which the current guardrails
cannot catch.

## Category E: retry does not reliably learn from its own error message

**t2_13** ("orders placed by customers based in Germany") failed
identically on both attempts:

```sql
-- attempt 1
WHERE dim_customer.nation_key = (SELECT nation_key FROM dim_region WHERE name = 'Germany')
-- error: Binder Error: Referenced column "name" not found in FROM clause!
--        Candidate bindings: "address", "nation_key", ..., "nation_name"

-- attempt 2 (after the error above was fed back)
WHERE dc.nation_key = (SELECT nation_key FROM dim_region WHERE name = 'Germany')
-- identical mistake
```

DuckDB's own error message names the correct column
(`"nation_name"`) in its candidate-bindings list, but the retry did not
pick it up. This matters for interpreting Day 12's self-correction
result (+0.020 lift, 1 of 4 triggered retries rescued): retry reliably
fixes *some* failure classes (Day 12's rescued case) but is not a
general fix for a wrong mental model of the schema — feeding back a raw
DuckDB error is a weaker signal than feeding back the actual candidate
column names in structured form would be.

## Category F: surrogate date keys treated as native timestamps

**t2_14** ("total revenue in the most recent quarter of data we have")
failed on both attempts with the same root cause:

```sql
WHERE order_date_key >= date_trunc('quarter', current_date) - interval '3 months'
-- error: Cannot compare values of type INTEGER and type TIMESTAMP
```

`order_date_key` is an integer foreign key into `dim_date`, not a date
column — `fact_orders.yml` documents it as such ("Foreign key to
dim_date.date_key"). The model treated it as a native timestamp on both
attempts, and separately used `current_date` (today's real-world date)
to mean "most recent," when TPC-H's generated data does not extend to
the present — the question needed `MAX(date)` from `dim_date`, not
`CURRENT_DATE`. Two compounding misunderstandings in the same query,
neither corrected by retry.

## Category G: a genuine documentation ambiguity, not a model error

**t1_11** ("How many order lines are currently open?") generated
`WHERE line_status = 'O'` (300,716 rows) against a golden definition of
`WHERE order_status = 'O'` (291,303 rows, `evaluation/
golden_questions.jsonl`). `fact_orders.yml` documents *both* columns as
plausible candidates — `order_status` ("Order header status: 'O'
(open)...") and `line_status` ("Line fulfilment status, 'O' (open)...")
— and, at the time this question was answered, nothing in the semantic
layer disambiguated which one "order lines... open" should mean. This
was a real gap in the semantic layer's documentation, not a model
hallucination: the model picked a real, correctly-described, defensible
column. Fixed in this session by adding a caveat to `fact_orders.yml`
that states this project's convention explicitly (order-level status
for "order lines... open/filled" phrasing); not re-run against the
model afterwards, since a single question's outcome on a
non-deterministic API isn't a meaningful before/after test on its own.

## Note on non-determinism

`t2_07` ("which market segment generates the most revenue") failed in
Day 12's run but succeeded cleanly when re-run here with identical
inputs. `chat_openai_compatible` (`src/llm_client.py`) does not pin a
temperature (see the same note in `evaluation/results/
self_correction_eval.md`), so a portion of any single run's failures
are not systematic — they would not reproduce on a re-run. This is
disclosed rather than treated as resolved: the categories above (A
through G) are the ones that reproduced or were traced to a specific,
inspectable cause, not an exhaustive list of every failure this system
could produce.

## Summary for the README's Limitations section

- The semantic layer measurably prevents grain mistakes (Category A) —
  this is the mechanism behind the Tier-3 ablation's headline result,
  not just a correlated number.
- `validate_result` is a plausibility heuristic, not a correctness
  oracle: it cannot catch a wrong dimension (B), a silently-empty
  false answer from a casing mismatch (D), or a wrong label column on
  an otherwise-correct aggregation (C).
- The retry loop reliably fixes some failures (Day 12: 1 rescue from 4
  triggered retries) but does not reliably correct a wrong mental
  model of the schema, even when the database's own error message
  names the fix (E, F).
- Execution-accuracy-by-exact-match (the methodology used throughout
  Days 10-14) cannot distinguish "logically correct, wrong label
  column" from "logically wrong" (C) — a real methodology caveat, not
  only a model one.
- At least one genuine documentation gap in the semantic layer itself
  was found and fixed (G).
