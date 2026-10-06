"""EXPLICIT PAID COMMAND: real 100-review cold/warm pilot on data/cost_100.csv (unchanged).

Cold run: empty result cache (fresh work/pilot/), ONE worker, full pipeline (enrich, declared verification
sample, group, rank, aggregates, memo). Warm run: identical command again on saved state -> must make zero
new enrichment calls. Saves evidence into cost/ for offline replay by cost/calculator.py.

  python3 cost/pilot.py --execute            # spends money (OpenAI); refuses to overwrite existing evidence
  python3 cost/pilot.py --execute --force    # re-run cold pilot, replacing previous evidence

Without --execute this script does nothing but print this help.
"""

import argparse
import csv
import gzip
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import run as orchestrator  # noqa: E402
from pipeline.common import file_sha  # noqa: E402

COST = ROOT / "cost"
INPUT = ROOT / "data" / "cost_100.csv"
EXPECTED = "c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e"
NAME = "pilot"
VERIFY_SAMPLE = 20


def pipeline_args(a):
    return ["--input", str(INPUT), "--name", NAME, "--workers", "1", "--batch-size", "50",
            "--enrich-provider", a.provider, "--enrich-model", a.model, "--enrich-effort", a.effort,
            "--budget", str(a.budget), "--verify-sample", str(VERIFY_SAMPLE),
            "--verify-provider", a.verify_provider, "--verify-model", a.verify_model,
            "--downstream-provider", a.provider, "--downstream-model", a.model]


def main():  # noqa: C901
    global COST, NAME
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="actually run the paid pilot")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--effort", default="none")
    ap.add_argument("--verify-provider", default="ollama")
    ap.add_argument("--verify-model", default="gemma4:e4b")
    ap.add_argument("--budget", type=float, default=0.50, help="USD cap for pilot enrichment")
    ap.add_argument("--name", default=NAME, help="run name (work/<name>, outputs/runs/<name>)")
    ap.add_argument("--evidence-dir", default=str(COST), help="where pilot evidence is written (default cost/)")
    a = ap.parse_args()
    COST, NAME = Path(a.evidence_dir), a.name
    COST.mkdir(parents=True, exist_ok=True)
    if not a.execute:
        print(__doc__)
        return
    if file_sha(INPUT) != EXPECTED:
        raise SystemExit("cost_100.csv checksum does not match manifest.json")
    if (COST / "pilot_calls.jsonl").exists() and not a.force:
        raise SystemExit("Pilot evidence already exists in cost/. Use --force to spend money on a new cold pilot.")
    work, run_dir = ROOT / "work" / NAME, ROOT / "outputs" / "runs" / NAME
    shutil.rmtree(work, ignore_errors=True)   # empty result cache for the cold experiment
    shutil.rmtree(run_dir, ignore_errors=True)

    timing = {}
    for phase in ("cold", "warm"):
        n_before = sum(1 for _ in open(run_dir / "calls.jsonl")) if (run_dir / "calls.jsonl").exists() else 0
        t0 = time.time()
        manifest = orchestrator.main(pipeline_args(a))
        wall = time.time() - t0
        calls = [json.loads(l) for l in open(run_dir / "calls.jsonl")][n_before:] if (run_dir / "calls.jsonl").exists() else []
        timing[phase] = {"wall_clock_s": round(wall, 3), "stage_seconds": manifest["invocations"][-1]["stage_seconds"],
                         "new_calls": len(calls), "new_enrich_calls": sum(c["role"] == "enrich" for c in calls)}
        with (COST / "pilot_calls.jsonl").open("w" if phase == "cold" else "a", encoding="utf-8") as f:
            for c in calls:
                f.write(json.dumps({**c, "pilot_phase": phase}, ensure_ascii=False) + "\n")
        print(f"[pilot] {phase}: {timing[phase]}")

    # one status per pilot ID, contract format
    with gzip.open(run_dir / "records.jsonl.gz", "rt", encoding="utf-8") as src, \
            (COST / "pilot_records.jsonl").open("w", encoding="utf-8") as dst:
        for line in src:
            dst.write(line)
    # usage.csv: one row per attempted call with its billing items
    with (COST / "usage.csv").open("w", newline="", encoding="utf-8") as f:
        cols = ["pilot_phase", "request_id", "role", "provider", "model", "effort", "tier", "outcome", "attempt",
                "retry_kind", "batch_size", "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens",
                "latency_s", "local_compute_s", "ts"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for line in open(COST / "pilot_calls.jsonl", encoding="utf-8"):
            w.writerow(json.loads(line))
    meta = {"input": "data/cost_100.csv", "input_sha256": EXPECTED, "verify_sample_declared": VERIFY_SAMPLE,
            "workers": 1, "batch_size": 50, "enrich": {"provider": a.provider, "model": a.model, "effort": a.effort},
            "verify": {"provider": a.verify_provider, "model": a.verify_model},
            "group_memo": {"provider": a.provider, "model": a.model}, "timing": timing,
            "run_manifest": json.loads((run_dir / "run_manifest.json").read_text()),
            "records_summary": json.loads((run_dir / "records_summary.json").read_text())}
    (COST / "pilot_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("[pilot] evidence saved to cost/. Now run: python3 cost/calculator.py")


if __name__ == "__main__":
    main()
