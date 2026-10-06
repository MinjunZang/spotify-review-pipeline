"""Orchestrator: one command runs every stage on an input CSV - no chat pasting.

  ingest -> enrich -> records -> verify -> group -> rank -> aggregates -> memo

Code owns dispatch, state, validation, budgets and logs; models are called only by enrich / verify /
group / memo. State lives in work/<name>/pipeline.sqlite; evidence goes to outputs/runs/<name>/.
Re-running the same command resumes: ingestion is skipped when the DB exists, completed IDs are never
re-sent, and group/memo reuse saved outputs when their evidence packs are unchanged.

Example:
  python -m pipeline.run --input data/cost_100.csv --name pilot_cold --budget 0.50 --verify-sample 20
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

from . import aggregates, enrich, group, ingest, memo, rank, records, verify
from .common import OUTPUTS, ROOT, WORK, append_jsonl, file_sha, now_iso, write_json
from .schema import prompt_hash

STAGES = ["ingest", "enrich", "records", "verify", "group", "rank", "aggregates", "memo"]


def git_rev():
    try:
        rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = subprocess.call(["git", "diff", "--quiet"], cwd=ROOT) != 0
        return rev + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--name", required=True, help="run name: work/<name>/, outputs/runs/<name>/")
    ap.add_argument("--stages", default=",".join(STAGES))
    ap.add_argument("--enrich-provider", default="openai")
    ap.add_argument("--enrich-model", default="gpt-6-luna")
    ap.add_argument("--enrich-effort", default="none")
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rpm", type=float, default=300)
    ap.add_argument("--budget", type=float, default=0.5, help="USD cap for enrichment in this run dir")
    ap.add_argument("--max-batches", type=int)
    ap.add_argument("--time-limit", type=float)
    ap.add_argument("--snapshot")
    ap.add_argument("--phase", default="auto")
    ap.add_argument("--verify-provider", default="ollama")
    ap.add_argument("--verify-model", default="gemma4:e4b")
    ap.add_argument("--verify-sample", type=int, help="declared verification sample size (default 1%%, max 1500)")
    ap.add_argument("--downstream-provider", default="openai", help="group + memo")
    ap.add_argument("--downstream-model", default="gpt-6-luna")
    ap.add_argument("--memo-effort", default="low")
    ap.add_argument("--finalize", action="store_true", help="write still-pending rows as quarantined")
    a = ap.parse_args(argv)

    stages = a.stages.split(",")
    db = WORK / a.name / "pipeline.sqlite"
    run_dir = OUTPUTS / "runs" / a.name
    run_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / "run_log.jsonl"
    timings = {}
    t_all = time.time()

    def stage(name, fn):
        if name not in stages:
            return None
        t0 = time.time()
        append_jsonl(log, {"ts": now_iso(), "stage": name, "event": "stage_start"})
        result = fn()
        timings[name] = round(time.time() - t0, 2)
        append_jsonl(log, {"ts": now_iso(), "stage": name, "event": "stage_end", "seconds": timings[name]})
        return result

    if db.exists() and "ingest" in stages:
        print(f"[run] {db} exists -> skipping ingestion (resume). Delete work/{a.name}/ for a cold run.")
        stages.remove("ingest")
    stage("ingest", lambda: ingest.ingest(a.input, db, run_dir / "ingestion"))
    e = stage("enrich", lambda: enrich.main([
        "--db", str(db), "--run-dir", str(run_dir), "--provider", a.enrich_provider, "--model", a.enrich_model,
        "--effort", a.enrich_effort, "--batch-size", str(a.batch_size), "--workers", str(a.workers),
        "--rpm", str(a.rpm), "--budget", str(a.budget), "--phase", a.phase]
        + (["--max-batches", str(a.max_batches)] if a.max_batches is not None else [])
        + (["--time-limit", str(a.time_limit)] if a.time_limit else [])
        + (["--snapshot", a.snapshot] if a.snapshot else [])))
    stage("records", lambda: records.write(db, run_dir, a.finalize))
    stage("verify", lambda: verify.main(["--db", str(db), "--run-dir", str(run_dir), "--provider", a.verify_provider,
                                          "--model", a.verify_model]
                                         + (["--sample-size", str(a.verify_sample)] if a.verify_sample else [])))
    stage("group", lambda: group.main(["--db", str(db), "--run-dir", str(run_dir), "--provider", a.downstream_provider,
                                        "--model", a.downstream_model]))
    stage("rank", lambda: rank.write(rank.compute(run_dir / "records.jsonl.gz", run_dir / "group" / "membership.csv"),
                                     run_dir / "ranking.csv"))
    stage("aggregates", lambda: aggregates.run(db, run_dir))
    stage("memo", lambda: memo.main(["--run-dir", str(run_dir), "--provider", a.downstream_provider,
                                      "--model", a.downstream_model, "--effort", a.memo_effort]))

    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"invocations": []}
    manifest.update({"run_name": a.name, "input": str(Path(a.input)), "input_sha256": file_sha(a.input),
                     "code_version": git_rev(),
                     "prompts": {p: prompt_hash(p) for p in ("enrich_v1", "verify_v1", "group_v1", "memo_v1")},
                     "settings": {k: v for k, v in vars(a).items() if k not in ("stages",)}})
    manifest["invocations"].append({"finished_at": now_iso(), "stages": stages, "stage_seconds": timings,
                                    "wall_clock_s": round(time.time() - t_all, 2),
                                    "enrich_stop_reason": (e or {}).get("stop_reason")})
    write_json(manifest_path, manifest)
    print(f"[run] done in {round(time.time() - t_all, 1)}s; stage seconds {timings}")
    return manifest


if __name__ == "__main__":
    main()
