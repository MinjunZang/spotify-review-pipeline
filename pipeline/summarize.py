"""Run summary from saved evidence (no model calls): usage, cost recomputed from rates, retries, failures,
timing, statuses and stop reasons.  Writes <run_dir>/run_summary.json.

  python -m pipeline.summarize --run-dir outputs/runs/full
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .common import write_json
from .llm import load_rates, usage_cost


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args(argv)
    run = Path(a.run_dir)
    rates = load_rates()
    calls = [json.loads(l) for l in open(run / "calls.jsonl", encoding="utf-8")]
    by_role = defaultdict(Counter)
    errors = Counter()
    unknown_cost = 0
    for c in calls:
        r = by_role[c["role"]]
        r["attempts"] += 1
        r["failed"] += c["outcome"] == "failed"
        r["retries"] += c.get("attempt", 1) > 1 or c.get("retry_kind") == "invalid_output_retry"
        for k in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"):
            r[k] += c.get(k) or 0
        cost = usage_cost(rates, c["provider"], c["model"], c["tier"], c)
        if cost is None:
            unknown_cost += 1
        r["api_cost_usd_e6"] += round((cost or 0) * 1e6)
        r["reviews_sent"] += len(c.get("review_ids") or [])
        if c.get("error"):
            errors[c["error"].split(":")[0]] += 1
    enrich_calls = [c for c in calls if c["role"] == "enrich"]
    t = sorted(ts(c["ts"]) for c in enrich_calls)
    summaries = sorted(run.glob("enrich_summary_*.json"))
    invocations = [json.loads(p.read_text()) for p in summaries]
    records = json.loads((run / "records_summary.json").read_text()) if (run / "records_summary.json").exists() else {}
    roles = {k: {**{x: v for x, v in r.items() if x != "api_cost_usd_e6"}, "api_cost_usd": round(r["api_cost_usd_e6"] / 1e6, 4)}
             for k, r in by_role.items()}
    out = {
        "calls": len(calls), "by_role": roles,
        "api_cost_usd": round(sum(r["api_cost_usd"] for r in roles.values()), 4),
        "calls_with_unknown_cost": unknown_cost,
        "error_types": dict(errors),
        "label_config": enrich_calls[-1]["label_config"] if enrich_calls else None,
        "enrich_first_call": t[0].isoformat() if t else None, "enrich_last_call": t[-1].isoformat() if t else None,
        "enrich_span_h": round((t[-1] - t[0]).total_seconds() / 3600, 2) if t else None,
        "enrich_wall_clock_h": round(sum(i["wall_clock_s"] for i in invocations) / 3600, 2),
        "enrich_invocations": [{k: i.get(k) for k in ("run_id", "phase", "workers", "batches_done", "wall_clock_s",
                                                      "stop_reason", "counts_after", "ledger")} for i in invocations],
        "records": records,
        "note": "Costs are recomputed from logged usage x cost/rates.csv; compare with the OpenAI usage dashboard.",
    }
    write_json(run / "run_summary.json", out)
    print(json.dumps({k: out[k] for k in ("calls", "api_cost_usd", "enrich_wall_clock_h", "error_types")}, indent=1))
    return out


if __name__ == "__main__":
    main()
