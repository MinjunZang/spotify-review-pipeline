# Cost & runtime calculator (100-review pilot)

## Offline replay — default, no API key, no model calls
```bash
python3 cost/calculator.py
```
Recomputes every charge from saved per-call usage (`pilot_calls.jsonl`) × editable rates (`rates.csv`) and writes
[`report.md`](report.md). Controls live in [`calculator_config.json`](calculator_config.json) or flags:
```bash
python3 cost/calculator.py --rate-multiplier 2      # API spend doubles; measured time and local cost do not change
python3 cost/calculator.py --budget 10 --workers 8 --tier batch --fallback-fraction 0.02
```

## Explicit paid pilot — separate command
```bash
python3 cost/pilot.py --execute
```
Refuses to run without `--execute`, refuses to overwrite existing evidence without `--force`, verifies the `cost_100.csv`
checksum, wipes the pilot's result cache (cold), runs the full pipeline with **1 worker**, then runs it again (warm).

## Files
| file | contents |
|---|---|
| `pilot_records.jsonl` | one contract-format record per pilot ID (100 completed, 0 quarantined) |
| `pilot_calls.jsonl` | every attempted call, cold and warm, with role, model, effort, tier, usage, latency, retry kind, request ID |
| `usage.csv` | the same attempts as a flat table of billing units |
| `rates.csv` | dated, editable prices with source links (checked 2026-10-06) |
| `pilot_meta.json` | input checksum, settings, cold/warm wall clock and stage times |
| `report.md` | measured-100 tables + full-run base/conservative scenarios with budget warnings |
| `alternatives/local_only_dryrun/` | a free local-only (Ollama) dry run of the same pilot: $0 API, but ~112 h projected — why a paid enricher was chosen |

## Measured vs projected vs actual
| | enrich API | wall clock |
|---|---|---|
| pilot, cold (100 rows, 1 worker) — **measured** | $0.0024 (all stages $0.0038) | 69.5 s |
| pilot, warm — **measured** | 0 new calls, $0 | 0.03 s |
| 500 checkpoint (2 workers) — measured | $0.0101 | 52 s enrich |
| 10,000 checkpoint (4 workers) — measured | $0.1893 | 490 s enrich |
| full run, **base projection** from the pilot (4 workers) | $11.39 | 9.2 h |
| full run, **actual** (8 workers, standard tier) | **$11.52** enrich, **$11.53** all roles | **3.9 h** enrichment |

The local verifier ran on the author's Apple M4 (24 GB): $0 API; its compute/electricity cost is unknown, not zero.
The OpenAI account was prepaid ($20, auto-reload off, $20 monthly limit) in addition to the pipeline's $15 ledger cap.
