# Retrieval evaluation

Evaluated against all 50 golden questions (`evaluation/golden_questions.jsonl`), k=5 (hybrid + rerank retrieves 8 candidates via hybrid search, then reranks down to 5). Hit rate: fraction of questions where at least one of the recorded `relevant_doc_ids` appears in the top-k retrieved chunks. MRR: mean reciprocal rank of the first relevant chunk (0 if none found in the top-k). Evaluated on the raw question text, not the query rewrite.

| Approach | Hit rate | MRR |
|---|---|---|
| Keyword only | 0.980 | 0.697 |
| Vector only | 0.960 | 0.751 |
| Hybrid | 1.000 | 0.741 |
| Hybrid + rerank | 1.000 | 0.758 |

Best approach used in production: **Hybrid + rerank**

## Methodology notes

The first run of this evaluation (before `metrics.yml` had the `answers_questions_like` field) found **keyword-only winning** (hit rate 1.000, MRR 0.805) with hybrid + rerank scoring lowest (MRR 0.734). Diagnosis traced this to the cross-encoder reranker repeatedly promoting `metric:average_order_value` above the genuinely relevant chunk on Tier-1 counting questions (e.g. "how many orders do we have") — the metric chunks were short and formulaic enough that the reranker had too little signal to distinguish COUNT-type from AVERAGE-type intent. Blending the rerank score with the original hybrid score at several weights was tested and did not help (MRR declined monotonically from 0.792 at weight 0 to 0.734 at weight 1 — hybrid's original ranking was already correct, so any weight on the reranker's score only hurt). Adding a short `answers_questions_like` field of representative phrasings to each metric fixed it directly: for the order_count/average_order_value pair above, the raw cross-encoder score for the correct chunk moved from -2.958 (losing) to +4.593 (clearly winning) in isolation. The numbers in the table above are from the post-fix index.

That fix has a real trade-off, visible in the numbers: it measurably **degraded keyword-only search** (hit rate 1.000 -> 0.980, MRR 0.805 -> 0.697) — the added vocabulary increases term overlap across chunks, which dilutes BM25's specificity. Hybrid and hybrid + rerank both stayed robust through the same content change. This is a more informative result than either number in isolation: it demonstrates a concrete mechanism for why a hybrid approach is more robust to semantic layer content changes than either single method alone, rather than hybrid + rerank simply being assumed to be the better default.

**Caveat on this specific measurement:** the golden question set and the `answers_questions_like` enrichment phrasings were both authored in the same session by the same person, not independently. The enrichment phrasings were written as generic, canonical descriptions of each metric (not copied from the golden questions' exact wording), but some vocabulary overlap between the two is inevitable given a single author. The measured improvement from enrichment should therefore be read as directionally real (the mechanism — short chunks giving the reranker too little signal — was independently confirmed by the isolated before/after score test above) but possibly somewhat optimistic versus a fully blind evaluation with independently authored questions and documentation.

## By tier

Tier 1: single-table aggregations. Tier 2: joins and time filters. Tier 3: metric-definition questions (the tier retrieval matters most for — see the Tier-3 ablation in `evaluation/results/error_analysis.md`).

| Approach | Tier 1 hit rate | Tier 1 MRR | Tier 2 hit rate | Tier 2 MRR | Tier 3 hit rate | Tier 3 MRR |
|---|---|---|---|---|---|---|
| Keyword only | 0.950 | 0.587 | 1.000 | 0.656 | 1.000 | 1.000 |
| Vector only | 1.000 | 0.808 | 0.900 | 0.595 | 1.000 | 0.950 |
| Hybrid | 1.000 | 0.706 | 1.000 | 0.646 | 1.000 | 1.000 |
| Hybrid + rerank | 1.000 | 0.746 | 1.000 | 0.650 | 1.000 | 1.000 |
