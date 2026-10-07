# Spotify review pipeline — where should next quarter's product effort go?

A multi-agent pipeline that turns all **660,622** Google Play reviews of Spotify (2022-05-17 → 2023-11-15) into a
product recommendation backed by traceable evidence. Code controls dispatch, state, validation, budgets and arithmetic;
models are used only for bounded language judgments in four separate roles (enrich, verify, group, memo).

| | |
|---|---|
| **Live dashboard** (no login) | **https://spotify-review-dashboard-eight.vercel.app** — overall metrics, issue ranking, AI recommendation with hoverable claim IDs, per-review trace |
| **Decision memo** | [`outputs/runs/full/memo/memo.md`](outputs/runs/full/memo/memo.md) · claims [`grading/claims.csv`](grading/claims.csv) + [`claims_extra.csv`](outputs/runs/full/memo/claims_extra.csv) |
| **Grading export** | [`grading/`](grading/) (contract format; self-check result below) |
| **Interruption/resume recording** | [GitHub release `evidence-v1`](https://github.com/MinjunZang/spotify-review-pipeline/releases/tag/evidence-v1) (`interrupt_resume_demo.mp4`, 5 min) |
| **Cost calculator** | [`cost/`](cost/) — `python3 cost/calculator.py` (offline) · measured report [`cost/report.md`](cost/report.md) |
| **Final full run** | `outputs/runs/full/` · run ID `20261006T142824-e6d6d0` (+ initial `20261006T142159-e9b882`, repair `20261006T181638-5e9ad1`) |
| **Large artifacts** | release `evidence-v1`: `grading.zip` (the grading folder as one download), `enriched.csv.gz` (labels + source values for every row), `calls_full.jsonl.gz` (every attempt with usage) |
| **Raw data** (not committed) | [course Google Drive ZIP](https://drive.google.com/file/d/1P0rUoAS_wVjp3BYKqXMEyD4u0uJP1Bvf/view) → put `spotify_reviews_18months.csv` in `data/`. SHA-256 `1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6` (97,400,616 bytes) |

---

## 1. Results summary

**Measured** = produced by a real run and saved in this repo. **Estimate** = projection, labelled as such.

| | value | evidence |
|---|---|---|
| Source rows ingested and accounted for | **660,622 / 660,622** (0 missing, 0 duplicate IDs) | [`ingestion_report.json`](outputs/runs/full/ingestion/ingestion_report.json), self-check |
| Completed classifications | **660,595** of 660,609 nonempty (**99.998%**) | [`records_summary.json`](outputs/runs/full/records_summary.json) |
| …of which via exact-text cache reuse | 176,420 rows (484,175 distinct texts sent to the model) | `cache_source_id` in `grading/records.jsonl.gz` |
| Quarantined | **27** = 13 `empty_review_text` + 14 nonempty model failures (9 quote not in source, 5 call failed) | [`quarantine.jsonl`](outputs/runs/full/quarantine.jsonl) |
| Golden 50 agreement (full-run labels) | topic **86%**, intent **92%**, severity exact **82%** (MAE 0.30), sentiment ±0.5 **86%** | [`evals/golden/full_run/report.md`](evals/golden/full_run/report.md) |
| Independent verifier (1,500 blind re-labels, different model) | topic 78.2%, intent 90.3%, severity exact 77.6% (±1: 98.7%); 448 disagreements; planted errors caught 150/150 | [`verify_report.json`](outputs/runs/full/verify/verify_report.json) |
| System tests | retry paths, quarantine, empty+cache, budget stop, resume, prompt injection (gpt-6-luna) — **all pass** | [`evals/system_tests/results.json`](evals/system_tests/results.json) |
| API spend, full run (all roles) — measured | **$11.53** (enrich $11.522, group + memo incl. reruns $0.013, verify $0 local) | [`run_summary.json`](outputs/runs/full/run_summary.json) |
| API spend, everything incl. pilot/checkpoints/evals — measured | **$11.75** (full $11.534, 10k $0.192, 500 $0.013, pilot $0.004, golden/smoke/injection $0.001) | every `calls.jsonl` × `cost/rates.csv` |
| Enrichment wall clock, full run — measured | **3.9 h** (8 workers, batch 50) + 37 min local verification | `run_summary.json`, `run_manifest.json` |
| Full-run cost projected from the 100-review pilot — estimate | base $11.39 / conservative $15.67 (actual landed 1.2% above base) | [`cost/report.md`](cost/report.md) |
| Course checker (`check_submission.py check`) | coverage point candidate **1.0**; only flag `unfinished_classification: 14` (the 14 nonempty quarantines, disclosed) | section 9 |

---

## 2. Recommendation (memo summary)

> **Next quarter: put the primary effort on billing/support — specifically the free-tier paywall experience
> (`billing.premium_paywall`) — and run playback reliability (`playback.playback_stops_or_skips`, `playback.crash_freeze`)
> as the funded secondary track.**

* `billing.premium_paywall` is the #1 issue in the baseline ranking: **49,834** complaints [C001], severity sum **141,749** [C002],
  mean severity 2.844423 [C003]. Billing/support's share of all completed reviews rose from **3.92%** [T009] (Jun–Nov 2022) to
  **13.04%** [T012] (May–Oct 2023) — the largest increase of any actionable area — and it carries the most cancellation-intent
  reviews of any area (10,964 [A012]).
* It is mostly a **policy** problem (restricted controls, skip limits, "can't choose a song" on the free tier), not a defect, so the work
  is product/pricing design: which controls to gate, how limits are communicated, and entitlement bugs (`billing.subscription_entitlement`, rank 12).
* **Alternatives.** Playback has the most blocked-task complaints of any area (11,130 at severity ≥ 4 [A020], 26.54% of its complaints [A021]; mean 3.188184 [A017]) but its
  share of reviews fell from 8.11% [T033] to 4.55% [T036] — keep a reliability track, not the headline. Access is the most severe area
  (mean 3.864256 [A038]) but small (3.33% of complaints [A039]). Usability is the largest area (82,828 complaints [A001]) but low severity
  (2.506640 [A003]) and led by ads/UI changes. `other.general` (rank 2, 66,259 [C005]) is generic dissatisfaction with no specific
  defect and is not actionable on its own.
* **Representative reviews:** `51f9fa20-daa1-49b5-9ef2-83a382686c0b` (paywall → switching apps), `c917e047-2d4b-41c5-ad41-bc9355b6d6e4`,
  `8ce24dbe-f1fe-45cd-bd15-dc210575e5c6` (skip limits).
* **Limitations:** self-selected public reviews, not a customer population; cancellation = expressed intent, not churn; no revenue data;
  0.002% of nonempty reviews unclassified; topic boundaries (paywall vs usability) are the noisiest labels (section 6).

The AI memo ([`memo.md`](outputs/runs/full/memo/memo.md), `gpt-6-luna`, prompt `memo_v2`) was generated from saved aggregates only and
passed the code check (every number equals its cited claim; every issue/review ID is in the evidence pack). Its reasoning was then read
and checked by a person — **the student reviewed this reasoning and endorses the recommendation above (2026-10-06)**; earlier memo versions and why they changed are kept in `outputs/runs/full/memo/history/` and [docs/failures.md](docs/failures.md) §4–5.

---

## 3. Rubric → evidence map

| Rubric item | Where to look |
|---|---|
| **D1 Accessible code/setup and artifacts** | section 8 (setup, commands, versions); `.env.example`; everything except the raw CSV is in the repo or the release |
| **D2 Architecture, shared schema, provenance** | [docs/architecture.md](docs/architecture.md) (diagram, code vs model, stop/retry); [labels/LABELS.md](labels/LABELS.md); [pipeline/schema.py](pipeline/schema.py); `label_config` on every record; `run_manifest.json` (code version, prompt hashes, settings) |
| **D3 Memo numbers ↔ calculations ↔ evidence** | `grading/claims.csv` (C IDs, checked by the course checker) + `claims_extra.csv` (A/T/K IDs); code check in `memo.json`; dashboard hover chips |
| **D4 Recommendation, alternatives, limitations** | section 2; memo; section 10 |
| **T1 50 human labels, per-field comparison, error analysis** | [evals/golden/](evals/golden/) — human file, per-case CSV, confusion table, [error_analysis.md](evals/golden/error_analysis.md) (incl. label provenance) |
| **T2 Independent verification, planted errors, injection** | `outputs/runs/full/verify/` (blind re-labels, disagreements, planted-error test); `evals/system_tests/results.json` (injection with gpt-6-luna) |
| **T3 Real 100-review cold/warm pilot, calculator, retry/spend/recovery controls** | [cost/](cost/) (pilot evidence, offline calculator, report); system tests `retry_paths`, `budget_stop`, `resume`; recording |
| **W1 Full ingestion, coverage, classification** | section 1; `grading/ingestion.json` (byte-identical to the checker's profile); self-check |
| **W2 Staged program, bounded calls, saved handoffs, resume** | `python -m pipeline.run --input <csv>`; ≤ 50 reviews/request in `calls.jsonl`; checkpoints + recording |
| **W3 Reproducible ranking + deployed dashboard/backend/DB with grounded AI recommendation** | `python -m pipeline.rank …` (section 8); per-issue [`aggregates.csv`](outputs/runs/full/aggregates.csv) and [`ranking.csv`](outputs/runs/full/ranking.csv); live dashboard; [dashboard/](dashboard/) (Vercel API → Neon Postgres) |

---

## 4. Architecture

Six stages, four model roles, everything else code. Full diagram and the code-vs-model table: **[docs/architecture.md](docs/architecture.md)**.

```mermaid
flowchart LR
    A[CSV] --> B[1 Prepare<br/>code] --> C[2 Classify<br/>enrich: gpt-6-luna] --> D[3 Verify<br/>verify: gemma4 local]
    C --> E[4 Group<br/>code membership + group: gpt-6-luna names] --> F[5 Rank<br/>code] --> G[6 Recommend<br/>code claims + memo: gpt-6-luna + code check]
    C & F & G --> H[(saved artifacts)] --> I[(Neon Postgres)] --> J[Vercel API] --> K[Dashboard]
```

| Role | Input | Output | Why a model is needed / what code does instead |
|---|---|---|---|
| **enrich** (`gpt-6-luna`, effort `none`, prompt `enrich_v1`, strict JSON schema, ≤ 50 reviews/request) | review text only | topic.subtopic, intent, severity, sentiment, quote span, needs_review | Reading messy multilingual text needs language judgment. Code: batching, budget, ID/enum/range validation, exact-substring quote check, entity extraction from a fixed term list, cache reuse, retries, statuses. |
| **verify** (`gemma4:e4b` via Ollama, prompt `verify_v1`) | text of a seeded 1,500-record sample, **never** the first labels | blind labels | An independent second opinion from a different model family. Code samples, compares, and plants errors. |
| **group** (`gpt-6-luna`, prompt `group_v2`) | bounded evidence pack (≤ 6 quotes per issue + counts) | issue names/descriptions, off-topic flags | Naming needs language. **Membership is code** (`topic.subtopic`, one issue per complaint), so the model cannot change counts. |
| **memo** (`gpt-6-luna`, effort `low`, prompt `memo_v2`) | claims + top-10 issues with 3 quotes each + trend + limitations | priority area, headline, memo | Weighing alternatives is judgment. Code computes every number, checks every cited number/ID, retries once with the problems listed. |

---

### Why these tools (measured quality, cost, runtime)

| option | measured | decision |
|---|---|---|
| **gpt-6-luna, effort `none`, 50 reviews/request** | pilot: 100/100 valid, $0.0024 enrich, 26 s; 10k: $0.19, 8 min (4 workers); golden topic 88% / intent 96% (pre-run) | **chosen enricher** — cheapest tested setting that passed evaluation; full run $11.52 in 3.9 h |
| local `gemma4:e4b` (Ollama) as enricher | same pilot: $0 API but 332 s for 100 reviews → projected ~112 h for the corpus ([`cost/alternatives/local_only_dryrun`](cost/alternatives/local_only_dryrun/report.md)) | too slow for the deadline; **used as the independent verifier** instead (different model family, $0) |
| Jev / TypeSafe (course suggestion) | not tested | not used: it would add a second paid provider and key; the brief allows any classifier, and the measured luna setup already met cost/quality needs. No claim is made about Jev's quality. |
| Sonnet 5 fallback | not run | declared fallback fraction 0; its rates stay in the calculator for what-if scenarios ($2/$10 per M tokens would make the full run ~20× more expensive) |
| SQLite (local state) + Postgres (deployed) | ingestion of 660,622 rows in 13 s; atomic per-batch commits | SQL/code for all counting, dedup, membership and ranking — no model involved |

## 5. Data and ingestion

`pipeline/ingest.py` reads every row with a multiline-safe CSV parser, keeps all six source strings unchanged, and computes
`source_sha256` with the course checker's own `row_sha`. Verified against the brief: **660,622** rows, **0** duplicate IDs, **13** empty
texts (quarantined as `empty_review_text`), **159,701** missing app versions (kept and classified — missing version is not a reason to skip),
**484,189** distinct nonempty texts (176,420 rows reuse an identical text). Ratings and monthly counts are in the report; the first
(2022-05) and last (2023-11) months are partial. Most repeated texts: "Good" ×12,845, "Nice" ×5,551, "Excellent" ×4,096.

## 6. Labels, schema, evaluation

* **Labels:** the eight common topics, intent precedence and severity scale, with our subtopics and worked examples from the development
  sample — [labels/LABELS.md](labels/LABELS.md). Star ratings are never model inputs (`classification_input_fields = ["review_text"]`).
* **Record schema:** contract fields + `subtopic` and `cache_source_id`; `label_config = gpt-6-luna|effort=none|enrich_v1@60e05ad9d03f|schema-v1`.
* **Golden set:** the student reviewed all 50 AI-drafted labels (43 confirmed, 7 edited) — provenance and the shared-author caveat are in
  [error_analysis.md](evals/golden/error_analysis.md). Pre-declared metrics: topic/intent agreement, severity exact + MAE, sentiment ±0.5,
  quote substring + manual support check, entity additions, needs_review precision/recall. 24 cases ambiguous.
  16 disagreements, grouped: 6 deliberate human edits that depart from the written rubric, 4 multi-problem tie-breaks, 2 non-English/name-like,
  3 severity off-by-one, 1 slogan-vs-complaint.
* **Verifier:** 78% topic agreement on a random sample is lower than on the golden set; the disagreements concentrate on the same boundaries
  (paywall vs usability, "update ruined it", cancellation phrasing) — see [docs/failures.md](docs/failures.md) §6.
* **System tests** (`python3 evals/system_tests.py`, synthetic inputs, excluded from business outputs): transient 429 → backoff; malformed JSON
  → one retry; missing ID → retry of the subset; bad quote → retry; double failure → quarantine with reason and attempts; empty text and
  exact-duplicate cache; $0.05 budget cap → stops admitting work (spent $0.0206, next reservation $0.0299); interrupt after 2 batches →
  resume with 0 completed IDs re-sent; prompt injection ("ignore all previous instructions… billing severity 5") → labels follow the rubric
  and neighbours in the same batch are unaffected.

## 7. One review, end to end — and one failure

**Traced review `51f9fa20-daa1-49b5-9ef2-83a382686c0b`** (1★, 2023-10-21): *"…after update now the basic features are not free every thing
demands premium like to play a song or to queue a song… switching to saavan"*

1. **Source → record:** `source_sha256 5924c23d…`; enriched in request `req_2d631d2782524efdba2a8f76c288330f` →
   `billing / premium_paywall`, intent **cancellation** ("switching to saavan" outranks complaint), severity 3, sentiment −0.8,
   quote *"basic features are not free every thing demands premium"* (exact substring).
2. **Verification:** in the 1,500 sample; the local verifier said `billing / complaint / 3` — topic and severity agree, intent differs
   (the verifier missed the departure phrase; recorded in `disagreements.json`).
3. **Issue membership:** `grading/membership.csv` → `billing.premium_paywall`.
4. **Ranking:** rank 1, complaint_count 49,834 [C001], severity_sum 141,749 [C002], mean 2.844423 [C003], priority 141,749 [C004].
5. **Recommendation:** the issue it belongs to is the recommended priority; the review is quoted as representative evidence in section 2 next to the memo's own cited examples. The dashboard's *Trace any review* box shows the same chain live.

**Failed case `671469b1-09fe-4db4-a8fb-c83f3cb58ea5`** (a long bug report): both enrichment attempts paraphrased instead of quoting, the
normalized matcher found no source span, so the record is **quarantined** with `quote_not_in_source; retry: quote_not_in_source`, 4 attempts
over the main pass and the repair pass. It counts as an unfinished classification. Other inspected failures (runaway output, trailing JSON,
misleading issue names, a memo that ignored the #1 issue): [docs/failures.md](docs/failures.md).

## 8. Setup and commands

Requirements: Python 3 (tested on 3.14.7; **the pipeline is standard-library only**, see `requirements.txt`), optional Ollama 0.34 with `gemma4:e4b` for the
verifier, `psycopg[binary]` 3.3 for the DB loader, Node 20+ with `@neondatabase/serverless` 1.2 for the dashboard API.

```bash
git clone https://github.com/MinjunZang/spotify-review-pipeline && cd spotify-review-pipeline
cp .env.example .env        # only needed for paid runs / DB loading; offline checks need no key
# put data/spotify_reviews_18months.csv from the course ZIP (checksum above)
```

**No API key needed (grader path):**
```bash
python3 cost/calculator.py                                   # offline cost/runtime replay
python3 -m pipeline.rank --records grading/records.jsonl.gz --membership grading/membership.csv --out /tmp/ranking.csv
cmp /tmp/ranking.csv grading/ranking.csv && echo identical   # deterministic baseline from saved outputs
python3 tools/check_submission.py profile --full data/spotify_reviews_18months.csv --out /tmp/ingestion.json
python3 tools/check_submission.py reference --full data/spotify_reviews_18months.csv --analysis data/spotify_reviews_18months.csv --out local-reference.json
python3 tools/check_submission.py check --reference local-reference.json --submission grading --out self-check.json
python3 evals/system_tests.py --only retry_paths,quarantine,empty_and_cache,budget_stop,resume   # fake provider, free
```

**Paid / model commands (explicit):**
```bash
python3 cost/pilot.py --execute                                            # 100-review cold+warm pilot
python3 -m pipeline.run --input data/spotify_reviews_18months.csv --name full --workers 8 --budget 15   # any CSV path works
./run_full.sh start | resume | status                                      # the full run as recorded
python3 evals/golden_eval.py --db work/full/pipeline.sqlite --tag full_run # golden comparison (no calls; needs the local state of a full run)
.venv/bin/python dashboard/load_db.py --run-dir outputs/runs/full          # load saved outputs into Postgres (needs DATABASE_URL)
```

**Database, backend and dashboard (reproduce the deployment):**
1. Create a Postgres database (we used a free [Neon](https://neon.tech) project, region `aws-us-east-1`, Postgres 17; ~215 MB after loading) and put its
   connection string in `.env` as `DATABASE_URL=…` (never committed).
2. Load the saved outputs — no model calls: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python dashboard/load_db.py --run-dir outputs/runs/full`.
   This creates tables `reviews` (660,622 rows), `issues`, `issue_examples`, `areas`, `trend`, `monthly`, `claims`, `memo`, `meta` (schema in `load_db.py`).
3. Deploy the API + page on Vercel from `dashboard/`: `vercel link`, then `vercel env add DATABASE_URL production`, then `vercel deploy --prod`.
   The browser never sees the connection string; it only calls `/api/overview`, `/api/ranking`, `/api/issue?id=…`, `/api/memo`, `/api/review?id=…`.
4. **Access:** the deployed dashboard is public — no login or key needed.

Re-running a command resumes: ingestion is skipped when the DB exists, completed IDs are never re-sent, and group/memo reuse saved outputs
when their evidence pack is unchanged (warm pilot: 0 calls).

## 9. Run evidence and controls

* **Model allowlist and settings:** enrich/group `gpt-6-luna` effort `none`; memo `gpt-6-luna` effort `low`; verifier `gemma4:e4b` (local).
  No stronger-model fallback was used (declared fallback fraction 0; Sonnet 5 rates kept in the calculator for what-if).
* **Spending control:** one shared ledger reserves worst-case cost (input estimate + max output tokens × retries) before every request and refuses
  dispatch when spent + reserved + next > cap ($15 for the full run; spent $11.52). Provider side: prepaid $20, auto-reload off, $20 monthly limit.
* **Retries:** ≤ 4 transient retries with exponential backoff + jitter; one invalid-output retry of the failing subset; 5 consecutive failed
  batches stop the run. Full run: 10,857 enrich attempts, 1,143 retries, 114 failed attempts (97 output-cap, 16 malformed, 1 network).
* **Interruption/resume:** recording in release `evidence-v1`. `grading/checkpoint_before.json` (119,741 completed IDs at Ctrl+C) ⊂
  `checkpoint_after.json` (660,595); calls are tagged `phase: initial` / `resume`; the checker found no completed ID re-sent after the checkpoint.
* **Requeues** after code fixes are logged with IDs in `outputs/runs/full/run_log.jsonl` (`event: requeue`).
* **Self-check output** (`check_submission.py check`): `working_coverage_point_candidate 1.0`; coverage `valid_completed 660,595`,
  `quarantined 27`, `valid_cache_reuses 176,420`, `missing 0`, `duplicate_ids 0`; `review_required` solely for `unfinished_classification: 14`.

## 10. Baseline ranking, trend, limitations

* **Baseline** ([`grading/ranking.csv`](grading/ranking.csv)): completed complaint + cancellation records only, one issue per record
  (`allow_multi_issue: false`), `priority = complaint_count × mean_severity = severity_sum`, sorted by score desc then issue ID; means to six
  decimals, half-up. Top 5: `billing.premium_paywall` 141,749 · `other.general` 131,797 · `usability.ads` 93,738 ·
  `playback.playback_stops_or_skips` 61,848 · `usability.ui_change` 50,043.
* **Trend** (complaint + cancellation reviews in the area ÷ all completed reviews; full months only; denominators 175,703 early, 301,428 late):

  | area | Jun–Nov 2022 | May–Oct 2023 |
  |---|---|---|
  | billing/support | 3.92% | **13.04%** |
  | other (generic) | 2.38% | 17.73% |
  | usability | 10.98% | 12.92% |
  | playback | 8.11% | 4.55% |
  | catalog | 2.18% | 3.08% |
  | access | 0.99% | 1.83% |
  | downloads | 1.29% | 0.74% |

  Review volume itself spikes in 2023-07 (85k) and 2023-10 (89k), so shares — not counts — are compared.
* **Limitations:** self-selected public reviews (complainers over-represented; 1★ = 37% of rows); no revenue, plan tier or churn; a
  cancellation label is stated intent; review text is untranslated (non-English reviews are classified directly, often as `unclear` with
  `needs_review`); 92,479 completed records carry `needs_review`; topic labels for paywalled controls vs usability are the least reliable
  (golden and verifier disagreements); severity is a single model judgment per review; 14 nonempty reviews (0.002%) are unclassified;
  the golden drafts and the prompts share an author (the AI assistant), so golden agreement may be optimistic.

## 11. Repository layout

```
pipeline/   ingest · enrich · verify · group · rank · aggregates · memo · records · export_grading · summarize · requeue · run (orchestrator) · llm · schema
prompts/    enrich_v1 · verify_v1 · group_v1/v2 · memo_v1/v2 (versioned; hashes in every label_config / run_manifest)
labels/     LABELS.md (shared definitions + examples)
evals/      golden/ (human labels, AI drafts, pre/full-run comparisons, error analysis) · system_tests.py + results
cost/       calculator, pilot, rates, usage, pilot records/calls, report, local-only alternative
outputs/runs/{pilot,checkpoint_500,analysis_10000,full}/   saved handoffs per run
grading/    standardized export for the course checker
dashboard/  Vercel API (api/*.js), static frontend (public/), Postgres loader (load_db.py)
docs/       architecture.md · failures.md
tools/      check_submission.py (course) · label_golden.py (local labeling UI)
```

**AI assistance:** the code, prompts and documentation were written with an AI coding assistant (Claude) at the student's direction, as the
assignment's starter prompt anticipates; golden labels were AI-drafted and human-reviewed (provenance per row). All numbers in this README
come from saved run outputs.
