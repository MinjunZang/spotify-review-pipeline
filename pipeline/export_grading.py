"""Export the standardized grading/ folder (GRADING_CONTRACT.md) from a finished run directory.

  python -m pipeline.export_grading --run-dir outputs/runs/full --out grading \
      --checkpoint-before outputs/runs/full/checkpoints/checkpoint_before.json \
      --checkpoint-after  outputs/runs/full/checkpoints/checkpoint_after.json
"""

import argparse
import gzip
import json
import shutil
from pathlib import Path

from .common import EXPECTED_SHA256, write_json

CALL_FIELDS = ["request_id", "role", "review_ids", "model", "phase", "outcome", "label_config", "input_tokens",
               "output_tokens", "cached_input_tokens", "reasoning_tokens", "cost_usd", "provider", "effort", "tier",
               "attempt", "retry_kind", "batch_id", "error", "inputs", "run_id", "ts"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", default="grading")
    ap.add_argument("--checkpoint-before", required=True)
    ap.add_argument("--checkpoint-after", required=True)
    a = ap.parse_args(argv)
    run, out = Path(a.run_dir), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ingestion = json.loads((run / "ingestion" / "ingestion.json").read_text())
    if ingestion["file_sha256"] != EXPECTED_SHA256:
        raise SystemExit("grading/ export is for the full course corpus only")
    write_json(out / "run.json", {"version": "a5-audit-v1", "analysis_count": ingestion["counts"]["records"],
                                  "analysis_sha256": EXPECTED_SHA256, "classification_input_fields": ["review_text"],
                                  "allow_multi_issue": False})
    shutil.copyfile(run / "ingestion" / "ingestion.json", out / "ingestion.json")
    shutil.copyfile(run / "records.jsonl.gz", out / "records.jsonl.gz")
    shutil.copyfile(run / "group" / "membership.csv", out / "membership.csv")
    shutil.copyfile(run / "ranking.csv", out / "ranking.csv")
    shutil.copyfile(run / "memo" / "claims.csv", out / "claims.csv")
    with open(run / "calls.jsonl", encoding="utf-8") as src, gzip.open(out / "calls.jsonl.gz", "wt", encoding="utf-8") as dst:
        for line in src:
            c = json.loads(line)
            dst.write(json.dumps({k: c.get(k) for k in CALL_FIELDS if k in c}, ensure_ascii=False) + "\n")
    for name, src in (("checkpoint_before.json", a.checkpoint_before), ("checkpoint_after.json", a.checkpoint_after)):
        cp = json.loads(Path(src).read_text())
        write_json(out / name, {"completed_ids": cp["completed_ids"], "taken_at": cp.get("taken_at"),
                                "run_id": cp.get("run_id"), "label_config": cp.get("label_config")})
    for stale in ("records.jsonl", "calls.jsonl"):  # checker rejects plain + .gz side by side
        (out / stale).unlink(missing_ok=True)
    print(f"[export] grading folder written to {out}")


if __name__ == "__main__":
    main()
