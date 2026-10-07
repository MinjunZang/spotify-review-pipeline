# Inspected failures and how they were handled

Every item below happened in a real run; evidence paths are given so it can be checked without re-running anything.

## 1. Model output continued after a complete JSON object (enrich)
* **Seen:** 2026-10-06 14:26, full run. `gpt-6-luna` sometimes returned a valid `{"results":[…]}` followed by more text
  (often a second copy). `json.loads` rejected the whole response → `malformed_output: Extra data`; after the one allowed retry,
  78 rows were quarantined in the first minutes. Evidence: failed calls in `outputs/runs/full/calls.jsonl`
  (`"error": "malformed_output: Extra data…"`).
* **Fix:** `pipeline/enrich.py` now parses the **first** complete JSON object (`json.JSONDecoder.raw_decode`) and logs a
  `trailing_output_ignored` event (314 events in `run_log.jsonl`). Every ID and field is still validated, so nothing is trusted blindly.
* **Recovery:** the run was stopped gracefully (SIGINT, in-flight batches committed), the 172 affected rows were requeued with a
  logged `requeue` event (`pipeline/requeue.py`, IDs listed in `run_log.jsonl`) and processed by the resumed run. Same model,
  prompt and schema, so `label_config` is unchanged.

## 2. Runaway output hitting the output-token cap (enrich)
* **Seen:** 97 attempts ended `incomplete: max_output_tokens` (the model kept repeating items until 6,000 tokens).
  After its one retry, a 50-review batch failing this way quarantined all 50 texts (≈ 200 rows by the end of the main pass).
* **Fix / recovery:** a logged repair pass requeued the 273 non-empty quarantines and re-ran them with **batch size 10** and a
  3,000-token cap (`run_log.jsonl` event `requeue` with note). 259 completed; **14 non-empty reviews remain quarantined** and
  are reported as unfinished classifications (`grading/records.jsonl.gz`, `outputs/runs/full/quarantine.jsonl`).
* **Cost of the failure:** the wasted output tokens are included in the reported spend ($11.52 enrich).

## 3. Evidence quote not an exact substring (enrich)
* **Seen:** the model sometimes changed case, whitespace or curly quotes when copying a span.
* **Fix:** `pipeline/schema.py::_normalized_find` locates the span ignoring case/whitespace/quote style and returns the
  **original source characters**, so `evidence_quote` remains an exact substring (checker: 0 `unsupported_quote`).
  9 reviews still failed after retry and remain quarantined, e.g. `671469b1-09fe-4db4-a8fb-c83f3cb58ea5`
  (a long bug report; both attempts paraphrased instead of quoting) — reason `quote_not_in_source; retry: quote_not_in_source`, 4 attempts.

## 4. Issue names generated from unrepresentative examples (group) → changed the memo's conclusion
* **Seen:** `group_v1` showed the naming model the **highest-severity** examples of each issue. For `other.general`
  (66,259 generic "worst app" complaints, mostly severity 2) the top-severity examples were rare privacy complaints, and the
  model named the whole issue *"Privacy and Data Collection Concerns"*; `usability.ui_navigation` became *"Privacy Controls and
  Navigation"*. Evidence: `outputs/runs/full/group/history/issues_group_v1.json`, `evidence_pack_v1.json`.
* **Impact:** membership and the ranking were unaffected (code owns both), but the memo cited the wrong name
  (`outputs/runs/full/memo/history/memo_v2_with_group_v1_names.json` calls `other.general` "generic privacy/data concerns").
* **Fix:** `group_v2` uses a representative pack (4 uniform-hash examples + 2 most severe), the severity distribution and the
  topic definition; names now match the members (*"General App Dissatisfaction"*).
* **Finding about the memo model:** with the wrong names the memo recommended **playback**; with corrected names (same numbers)
  it recommended **billing/support**. The AI recommendation is sensitive to framing, which is why the human-reviewed reasoning in
  the README, not the model output alone, is the final recommendation.

## 5. memo_v1 ignored the #1 ranked issue
* **Seen:** `memo_v1` recommended playback and dismissed `billing.premium_paywall` (rank 1, fastest-growing share) in one clause.
  Evidence: `outputs/runs/full/memo/history/memo_v1.md`.
* **Fix:** `memo_v2` requires the memo to address the top-ranked issues explicitly, to separate defects from deliberate pricing
  policy, to use trend claims, and to treat `other.general` as non-actionable. The code check (numbers ↔ claims, IDs ∈ pack) passed
  for every version.

## 6. Verifier disagreement is high on topic (verify)
* 1,500 blind re-labels by `gemma4:e4b`: topic agreement 78.2%, intent 90.3%, severity exact 77.6% (within ±1: 98.7%).
  448 of 1,500 records differ on topic, intent or severity by more than 1 (`outputs/runs/full/verify/disagreements.json`).
* Reading the disagreements, most are the same boundary cases as in the golden set: paywalled controls (billing vs usability),
  generic "update ruined the app" (usability.ui_change vs other), and cancellation phrasing ("switching to …") that the verifier
  labels as complaint. Example: `51f9fa20-daa1-49b5-9ef2-83a382686c0b` — "…switching to saavan" → enricher `cancellation` (correct by the
  contract's precedence), verifier `complaint`.
* The planted-error test (150 sampled records copied with a deliberately wrong topic and intent) was flagged 150/150 by the
  comparison — the verifier is independent enough to catch gross errors, but a single small local model is a noisy referee for
  fine boundaries.
