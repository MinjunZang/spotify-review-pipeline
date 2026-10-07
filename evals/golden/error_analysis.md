# Golden-set error analysis (final, full-run labels)

**What is compared.** The labels actually exported for the 50 golden review IDs in the full-corpus run
(`gpt-6-luna|effort=none|enrich_v1@60e05ad9d03f|schema-v1`) against `golden_50_human.csv`.
Numbers: [`full_run/summary.json`](full_run/summary.json) · per case: [`full_run/per_case.csv`](full_run/per_case.csv),
[`full_run/cases.json`](full_run/cases.json) · table: [`full_run/report.md`](full_run/report.md).
A pre-run check on the 50 texts alone is in [`pre_full_run/`](pre_full_run/report.md) (topic 88%, intent 96%, severity exact 72%).

| metric (n = 50; missing predictions would count as wrong — there were none) | strict | accepting the human's listed alternatives |
|---|---|---|
| topic agreement | **86%** | 96% |
| intent agreement | **92%** | 100% |
| severity exact agreement | **82%** (MAE 0.30) | 88% |
| sentiment within the pre-declared ±0.5 tolerance | 86% (MAE 0.146) | — |
| evidence quote is an exact source substring (code check) | 100% | — |
| needs_review as a prediction (vs the human flag) | precision 0.73, recall 0.67 | — |

Fifty cases are a small diagnostic sample, not a population accuracy estimate. 24 of 50 were marked ambiguous by the labeler.

## How the golden labels were made (provenance — read this first)

1. The reviewer (the student) asked the AI assistant to help label. The assistant (Claude) wrote **draft** labels
   with a one-line rationale per review (`golden_50_ai_draft.csv`), using only the shared definitions in `labels/LABELS.md`.
2. The student reviewed every one of the 50 in the local tool (`tools/label_golden.py`), which records provenance per row:
   **43 `human_confirmed`** (draft accepted unchanged) and **7 `human_edited`**.
3. The human labels were never model inputs, never used as prompt examples, and did not drive prompt changes. The prompt's
   definitions were written before the drafts; the only later prompt change was the compact output format (no rule changes).
4. **Limitation:** the same assistant wrote the prompts and the drafts, so agreement on the 43 confirmed cases may be inflated by
   a shared reading of the rubric. The instructor's private benchmark is the independent check.

## Disagreements (16 of 50) and what they show

| group | cases | finding | decision |
|---|---|---|---|
| **A. Human edits that depart from the written severity/topic rubric** | 5 "I just loved it" (human support/2), 7 "Excellent" (support/2), 9 "awesome and very diverse" (support/4), 6 "Hate this application 🤮" (sev 5), 20 "Hate This application 👎" (sev 4), 48 "This update very bad… old Spotify" (sev 4) | The model follows the shared definitions (generic praise → `other`, severity 1; generic criticism → severity 2; 5 is reserved for explicit financial/privacy/data harm). The human labeler confirmed these edits are their deliberate judgement. | Kept as the human labeled them; counted as disagreements. They account for 6 of the 16 disagreements and for most of the severity MAE. |
| **B. Multi-problem tie-breaks** | 38 lyrics + seeking (human catalog, model usability), 43 can't play chosen songs/rewind after update (human usability, model billing), 33 sudden loud ads (human usability, model playback), 47 price + ads (intent: human complaint, model cancellation for "Forget it") | Genuinely ambiguous: two equally severe problems or an implicit paywall. The model's choice is in the human's own accepted-alternatives list for 38, 33, 43 and 47. | No prompt change: the rule ("first specific problem on a tie") is applied inconsistently by both human and model when the "first" problem is unclear. Documented as a limitation of single-label topics. |
| **C. Non-English / name-like text** | 17 Tagalog "Lhat ng song nasa spotify" (human catalog/praise, model other/unclear), 28 "Unconditional love, Stoli Canales" (human praise, model unclear) | The model is conservative with short non-English text and possible names; both alternatives were pre-listed by the human. | Accepted; these are flagged as unsupported-language/ambiguous and carry little weight in issue ranking (not complaints). |
| **D. Severity off by one** | 1 political catalog complaint (2 vs 3), 11 playback stops (4 vs 3), 46 "too much ad" (3 vs 2) | Boundary between "annoyance" (2), "degraded" (3) and "blocked" (4) is the noisiest part of the scale; in each case the model's value is in the human's alternatives. | Kept; severity is reported with MAE and the ranking's sensitivity to severity is discussed in the README. |
| **E. Intent: bare slogan vs complaint** | 31 "I hate this app and sweden. I love islam" (human unclear, model complaint) | The contract says bare boycott slogans are `unclear` unless a product complaint is expressed; "I hate this app" can be read either way. | Accepted alternative. |

**needs_review:** the model flagged 11 cases and the human 12; recall 0.67 means a third of human-flagged ambiguous cases are not
flagged by the model, so `needs_review` is a useful but incomplete routing signal — it is not treated as a correctness guarantee.

**Quote support (manual inspection):** all 50 quotes are exact substrings (code check). For reviews of ≤ 20 words the
whole review is the quote by design. The 11 longer reviews (cases 1, 11, 12, 22, 25, 29, 32, 33, 41, 43, 44) were read one by one:
each quote contains the clause that carries the label (e.g. 29 starts "Deleting this App…" → cancellation; 32 "now I can't even
open the app" → blocked playback; 22 "Spotify gave me recommendations…" → catalog praise). Two quotes (11, 43) are longer than the
prompt's ~12-word guidance but still support the label. No quote cites praise to justify a complaint.
