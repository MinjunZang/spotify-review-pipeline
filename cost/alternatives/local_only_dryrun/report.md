# 100-review cost & runtime calculator — measured pilot and full-run projection

Offline replay of saved evidence; rates from `rates.csv`. No model calls were made to produce this report.

## Measured: 100-review pilot (`data/cost_100.csv`)

* Input SHA-256 `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e` · IDs: 100 · completed **100** · quarantined/failed **0** · unique texts sent 100 · result-cache hits 0
* Workers 1 · enrichment batch size 50 · declared verification sample 20 reviews
* **Cold** end-to-end wall clock: **9.5 min** · API spend **$0.0000** · calls 5
* **Warm** (saved results, unchanged settings): **0.0 s** · new enrichment calls **0** · all new calls 0 · incremental API spend $0.0000

| phase | stage | provider / model / effort / tier | requests | attempts | failed | retries | input tok | cached tok | output tok | reasoning tok | API cost | local compute |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cold | enrich | ollama / `gemma4:e4b` / none / local | 2 | 2 | 0 | 0 | 5,419 | 0 | 5,658 | 0 | $0.0000 | 5.5 min |
| cold | verify | ollama / `gemma4:e4b` / none / local | 1 | 1 | 0 | 0 | 1,248 | 0 | 510 | 0 | $0.0000 | 36.0 s |
| cold | group | ollama / `gemma4:e4b` / none / local | 1 | 1 | 0 | 0 | 3,067 | 0 | 1,113 | 0 | $0.0000 | 84.9 s |
| cold | memo | ollama / `gemma4:e4b` / low / local | 1 | 1 | 0 | 0 | 5,741 | 0 | 1,278 | 0 | $0.0000 | 115.0 s |
| warm | enrich | ollama / `gemma4:e4b` / none / local | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |
| warm | verify | ollama / `gemma4:e4b` / none / local | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |
| warm | group | ollama / `gemma4:e4b` / none / local | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |
| warm | memo | ollama / `gemma4:e4b` / low / local | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |

Prompt/schema versions (label_config): enrich: `gemma4:e4b|effort=none|enrich_v1@60e05ad9d03f|schema-v1`; verify: `gemma4:e4b|effort=none|verify_v1@ec6d869e3ca7`; group: `gemma4:e4b|effort=none|group_v1@3b594bed6ba2`; memo: `gemma4:e4b|effort=low|memo_v1@f1f824fe4b3e`

* Cost per 1,000 input rows (cold, all stages): **$0.0000** · per completed record: $0.0000
* Enrichment throughput (1 worker): 0.30 records/s (332.1 s for the stage) · stage seconds: ingest 0.01s, enrich 332.13s, records 0.01s, verify 36.03s, group 84.93s, rank 0.0s, aggregates 0.0s, memo 115.06s
* Summed call latency ≠ wall clock when calls overlap; wall clock above is measured with a clock around the whole command.

## Projection: full corpus

* Rows **660,622** = 660,609 nonempty classifications + 13 empty-text quarantines (no model call). Distinct nonempty texts with valid exact-text reuse: **484,189**.
* Measured per sent text (enrich, incl. its retries and the fixed prompt share at batch size 50): 54.2 input tok (0.0 cached), 56.6 output tok.
* Controls: budget **$15.00** · workers 4 · projected tier `local` · output-token cap 4000/request · fallback fraction 0.0% to `claude-sonnet-5` · verification 0.3% of texts, max 1,500 (local)
* Conservative: +25% tokens, +10% retried batches, ×1.5 time, ×3 group/memo (larger packs). Group + memo are fixed overhead, counted once.

| scenario | texts | enrich API | fallback API | verify (n, API) | group+memo API | **API total** | enrich time | verify time (local) | **total time** | budget |
|---|---|---|---|---|---|---|---|---|---|---|
| base, exact-text reuse | 484,189 | $0.0000 | $0.0000 | 1,453, $0.0000 | $0.0000 | **$0.0000** | 111.7 h | 43.6 min | **112.5 h** | within |
| conservative, exact-text reuse | 484,189 | $0.0000 | $0.0000 | 1,453, $0.0000 | $0.0000 | **$0.0000** | 184.3 h | 65.4 min | **185.5 h** | within |
| base, NO reuse | 660,609 | $0.0000 | $0.0000 | 1,500, $0.0000 | $0.0000 | **$0.0000** | 152.4 h | 45.0 min | **153.2 h** | within |
| conservative, NO reuse | 660,609 | $0.0000 | $0.0000 | 1,500, $0.0000 | $0.0000 | **$0.0000** | 251.4 h | 67.5 min | **252.7 h** | within |

**Separate from API spend:** local verifier compute (Ollama on the author's Apple M4, 24 GB) has no API charge; electricity/hardware cost is **unknown, not zero**, and is reported as time only. Delayed provider billing means the local ledger is not a guarantee; the OpenAI account also has a hard usage limit.

## Rates used (editable `cost/rates.csv`)

| provider | model | tier | item | USD per 1M units | source | checked |
|---|---|---|---|---|---|---|
| anthropic | claude-sonnet-5 | standard | input | 2.0000 | https://www.anthropic.com/news/claude-sonnet-5 | 2026-10-06 |
| anthropic | claude-sonnet-5 | standard | output | 10.0000 | https://www.anthropic.com/news/claude-sonnet-5 | 2026-10-06 |
| fake | fake-keyword-v1 | test | input | 0.0000 | synthetic test provider | 2026-10-06 |
| fake | fake-keyword-v1 | test | output | 0.0000 | synthetic test provider | 2026-10-06 |
| fake | fake-priced-v1 | test | input | 1.0000 | synthetic priced test model (budget-stop test only) | 2026-10-06 |
| fake | fake-priced-v1 | test | output | 1.0000 | synthetic priced test model (budget-stop test only) | 2026-10-06 |
| ollama | gemma4:e4b | local | input | 0.0000 | local inference (no API charge) | 2026-10-06 |
| ollama | gemma4:e4b | local | output | 0.0000 | local inference (no API charge) | 2026-10-06 |
| openai | gpt-6-luna | batch | input | 0.0500 | https://developers.openai.com/api/docs/models/gpt-6-luna | 2026-10-06 |
| openai | gpt-6-luna | batch | cached_input | 0.0050 | https://developers.openai.com/api/docs/models/gpt-6-luna | 2026-10-06 |
| openai | gpt-6-luna | batch | output | 0.2500 | https://developers.openai.com/api/docs/models/gpt-6-luna | 2026-10-06 |
| openai | gpt-6-luna | standard | input | 0.1000 | https://developers.openai.com/api/docs/models/gpt-6-luna | 2026-10-06 |
| openai | gpt-6-luna | standard | cached_input | 0.0100 | https://developers.openai.com/api/docs/models/gpt-6-luna | 2026-10-06 |
| openai | gpt-6-luna | standard | output | 0.5000 | https://developers.openai.com/api/docs/models/gpt-6-luna | 2026-10-06 |

Formula: `item_cost = billed_units × price_per_unit`; uncached input = input − cached input; reasoning tokens are already inside output and are not added again.
