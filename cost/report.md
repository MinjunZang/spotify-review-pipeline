# 100-review cost & runtime calculator — measured pilot and full-run projection

Offline replay of saved evidence; rates from `rates.csv`. No model calls were made to produce this report.

## Measured: 100-review pilot (`data/cost_100.csv`)

* Input SHA-256 `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e` · IDs: 100 · completed **100** · quarantined/failed **0** · unique texts sent 100 · result-cache hits 0
* Workers 1 · enrichment batch size 50 · declared verification sample 20 reviews
* **Cold** end-to-end wall clock: **69.5 s** · API spend **$0.0038** · calls 6
* **Warm** (saved results, unchanged settings): **0.0 s** · new enrichment calls **0** · all new calls 0 · incremental API spend $0.0000

| phase | stage | provider / model / effort / tier | requests | attempts | failed | retries | input tok | cached tok | output tok | reasoning tok | API cost | local compute |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cold | enrich | openai / `gpt-6-luna` / none / standard | 2 | 3 | 0 | 1 | 7,096 | 3,774 | 3,966 | 0 | $0.0024 | — |
| cold | verify | ollama / `gemma4:e4b` / none / local | 1 | 1 | 0 | 0 | 1,248 | 0 | 510 | 0 | $0.0000 | 28.5 s |
| cold | group | openai / `gpt-6-luna` / none / standard | 1 | 1 | 0 | 0 | 3,270 | 0 | 627 | 0 | $0.0006 | — |
| cold | memo | openai / `gpt-6-luna` / low / standard | 1 | 1 | 0 | 0 | 4,778 | 0 | 696 | 233 | $0.0008 | — |
| warm | enrich | openai / `gpt-6-luna` / none / standard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |
| warm | verify | ollama / `gemma4:e4b` / none / local | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |
| warm | group | openai / `gpt-6-luna` / none / standard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |
| warm | memo | openai / `gpt-6-luna` / low / standard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | — |

Prompt/schema versions (label_config): enrich: `gpt-6-luna|effort=none|enrich_v1@60e05ad9d03f|schema-v1`; verify: `gemma4:e4b|effort=none|verify_v1@ec6d869e3ca7`; group: `gpt-6-luna|effort=none|group_v1@3b594bed6ba2`; memo: `gpt-6-luna|effort=low|memo_v1@f1f824fe4b3e`

* Cost per 1,000 input rows (cold, all stages): **$0.0382** · per completed record: $0.0000
* Enrichment throughput (1 worker): 3.89 records/s (25.7 s for the stage) · stage seconds: ingest 0.0s, enrich 25.71s, records 0.01s, verify 28.57s, group 6.95s, rank 0.0s, aggregates 0.0s, memo 8.21s
* Summed call latency ≠ wall clock when calls overlap; wall clock above is measured with a clock around the whole command.

## Projection: full corpus

* Rows **660,622** = 660,609 nonempty classifications + 13 empty-text quarantines (no model call). Distinct nonempty texts with valid exact-text reuse: **484,189**.
* Measured per sent text (enrich, incl. its retries and the fixed prompt share at batch size 50): 71.0 input tok (37.7 cached), 39.7 output tok.
* Controls: budget **$15.00** · workers 4 · projected tier `standard` · output-token cap 4000/request · fallback fraction 0.0% to `claude-sonnet-5` · verification 0.3% of texts, max 1,500 (local)
* Conservative: +25% tokens, +10% retried batches, ×1.5 time, ×3 group/memo (larger packs). Group + memo are fixed overhead, counted once.

| scenario | texts | enrich API | fallback API | verify (n, API) | group+memo API | **API total** | enrich time | verify time (local) | **total time** | budget |
|---|---|---|---|---|---|---|---|---|---|---|
| base, exact-text reuse | 484,189 | $11.39 | $0.0000 | 1,453, $0.0000 | $0.0015 | **$11.39** | 8.6 h | 34.6 min | **9.2 h** | within |
| conservative, exact-text reuse | 484,189 | $15.66 | $0.0000 | 1,453, $0.0000 | $0.0044 | **$15.67** | 14.3 h | 51.8 min | **15.1 h** | ⚠️ EXCEEDS |
| base, NO reuse | 660,609 | $15.54 | $0.0000 | 1,500, $0.0000 | $0.0015 | **$15.55** | 11.8 h | 35.7 min | **12.4 h** | ⚠️ EXCEEDS |
| conservative, NO reuse | 660,609 | $21.37 | $0.0000 | 1,500, $0.0000 | $0.0044 | **$21.38** | 19.5 h | 53.5 min | **20.4 h** | ⚠️ EXCEEDS |

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
