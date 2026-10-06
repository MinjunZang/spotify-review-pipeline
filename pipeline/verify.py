"""Stage 3 - Verify (role: verify).

A separate model task re-labels a declared, seeded random sample of enriched records WITHOUT seeing the
first prediction (it gets only the review text + rubric). Code then compares the two and writes a
disagreement report. A planted-error test copies the sampled enriched labels, deliberately corrupts some,
and measures whether the comparison flags them (reuses the same verifier predictions; no extra calls).

Default verifier: local Ollama gemma4:e4b (a different model family from the enricher, zero API cost).

Usage: python -m pipeline.verify --db ... --run-dir ... [--sample-size 20 | --sample-rate 0.01 --max-sample 1500]
"""

import argparse
import hashlib
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path

from .common import TOPICS, append_jsonl, now_iso, write_json
from .llm import BudgetExceeded, RoleCaller
from .schema import prompt_hash, prompt_text, verify_json_schema

PROMPT = "verify_v1"
SEED = "verify-seed-v1"


def sample_ids(con, size, seed=SEED):
    """Deterministic sample of records actually sent to the enricher (originals, not cache aliases)."""
    ids = [r[0] for r in con.execute(
        "SELECT review_id FROM status WHERE status='completed' AND cache_source_id IS NULL AND request_id IS NOT NULL")]
    ids.sort(key=lambda rid: hashlib.sha256(f"{seed}:{rid}".encode()).hexdigest())
    return ids[:size]


def enriched(con, ids):
    q = f"""SELECT v.review_id, v.review_text, r.topic, r.intent, r.severity, r.sentiment
            FROM reviews v JOIN results r ON r.source_review_id=v.review_id
            WHERE v.review_id IN ({','.join('?' * len(ids))})"""
    return {row[0]: {"text": row[1], "topic": row[2], "intent": row[3], "severity": row[4], "sentiment": row[5]}
            for row in con.execute(q, ids)}


def compare(first, second):
    rows, agree = [], Counter()
    for rid, a in first.items():
        b = second.get(rid)
        if not b:
            continue
        d = {"review_id": rid, "topic_agree": a["topic"] == b["topic"], "intent_agree": a["intent"] == b["intent"],
             "severity_abs_diff": abs(a["severity"] - b["severity"]),
             "sentiment_abs_diff": round(abs(a["sentiment"] - b["sentiment"]), 2)}
        d["any_disagreement"] = not (d["topic_agree"] and d["intent_agree"] and d["severity_abs_diff"] <= 1)
        agree["topic"] += d["topic_agree"]
        agree["intent"] += d["intent_agree"]
        agree["severity_exact"] += d["severity_abs_diff"] == 0
        agree["severity_within1"] += d["severity_abs_diff"] <= 1
        agree["flagged"] += d["any_disagreement"]
        rows.append(d)
    n = len(rows)
    rates = {f"{k}_rate": round(agree[k] / n, 4) for k in ("topic", "intent", "severity_exact", "severity_within1", "flagged")} if n else {}
    return rows, {"compared": n, **rates,
                  "severity_mae": round(sum(r["severity_abs_diff"] for r in rows) / n, 4) if n else None}


def plant_errors(first, k, seed="planted-v1"):
    """Deliberately wrong test copy: change topic (and intent) for k records. Synthetic; never exported."""
    rng = random.Random(seed)
    ids = sorted(first)
    rng.shuffle(ids)
    planted, copy = [], {rid: dict(v) for rid, v in first.items()}
    for rid in ids[:k]:
        wrong_topic = rng.choice([t for t in TOPICS if t != first[rid]["topic"] and t != "other"])
        copy[rid]["topic"] = wrong_topic
        copy[rid]["intent"] = "praise" if first[rid]["intent"] != "praise" else "complaint"
        planted.append({"review_id": rid, "original_topic": first[rid]["topic"], "planted_topic": wrong_topic,
                        "original_intent": first[rid]["intent"], "planted_intent": copy[rid]["intent"]})
    return copy, planted


def run(args):
    run_dir = Path(args.run_dir)
    out = run_dir / "verify"
    con = sqlite3.connect(args.db)
    total = con.execute("SELECT COUNT(*) FROM status WHERE status='completed' AND cache_source_id IS NULL").fetchone()[0]
    size = args.sample_size or min(args.max_sample, max(1, round(total * args.sample_rate)))
    ids = sample_ids(con, size)
    first = enriched(con, ids)
    cfg = f"{args.model}|effort={args.effort}|{PROMPT}@{prompt_hash(PROMPT)}"
    preds_path = out / "verifier_predictions.jsonl"
    done = {}
    if preds_path.exists():  # resumable: skip IDs already verified under this config
        for line in preds_path.open(encoding="utf-8"):
            p = json.loads(line)
            if p["verify_config"] == cfg:
                done[p["review_id"]] = p
    todo = [rid for rid in ids if rid not in done]
    print(f"[verify] declared sample={size} of {total} sent originals; already verified={len(done)}; to call={len(todo)}")
    caller = RoleCaller(run_dir, "verify", args.provider, args.model, args.effort, args.max_output_tokens,
                        args.budget, cfg)
    system = prompt_text(PROMPT)
    stop_reason = "complete"
    for i in range(0, len(todo), args.batch_size):
        chunk = todo[i:i + args.batch_size]
        local = {f"r{j + 1}": rid for j, rid in enumerate(chunk)}
        user = "Label these reviews:\n" + json.dumps([{"id": k, "text": first[rid]["text"]} for k, rid in local.items()],
                                                     ensure_ascii=False)
        try:
            parsed, res = caller.call(system, user, verify_json_schema(), "verify_results", chunk)
        except BudgetExceeded as e:
            stop_reason = f"budget: {e}"
            break
        got = set()
        for item in (parsed or {}).get("results", []):
            rid = local.get(item.get("id"))
            if not rid or rid in got or item.get("topic") not in TOPICS or type(item.get("severity")) is not int:
                continue
            got.add(rid)
            p = {"review_id": rid, "topic": item["topic"], "intent": item.get("intent"), "severity": item["severity"],
                 "sentiment": item.get("sentiment", 0), "verify_config": cfg, "request_id": res.request_id}
            append_jsonl(preds_path, p)
            done[rid] = p
        print(f"[verify] {len(done)}/{size} verified (missing in this batch: {len(chunk) - len(got)})")

    rows, stats = compare(first, done)
    dis = [dict(r, enriched={k: first[r["review_id"]][k] for k in ("topic", "intent", "severity")},
                verifier={k: done[r["review_id"]][k] for k in ("topic", "intent", "severity")},
                text=first[r["review_id"]]["text"][:300]) for r in rows if r["any_disagreement"]]
    planted_copy, planted = plant_errors({k: first[k] for k in done}, max(1, len(done) // 10))
    _, planted_stats = compare({p["review_id"]: planted_copy[p["review_id"]] for p in planted}, done)
    report = {"generated_at": now_iso(), "verify_config": cfg, "enrich_records_available": total,
              "declared_sample_size": size, "sample_seed": SEED, "verified": len(done), "stop_reason": stop_reason,
              "agreement": stats, "disagreement_count": len(dis),
              "planted_error_test": {"synthetic": True, "planted": len(planted),
                                     "detected": planted_stats.get("flagged_rate"),
                                     "note": "Copies of sampled enriched labels with deliberately wrong topic+intent; "
                                             "detected = verifier disagrees. Not part of any business output.",
                                     "cases": planted},
              "verify_calls": len(caller.calls), "verify_cost_usd": round(sum(c["cost_usd"] or 0 for c in caller.calls), 6)}
    write_json(out / "verify_report.json", report)
    write_json(out / "disagreements.json", dis)
    print(f"[verify] agreement topic={stats.get('topic_rate')} intent={stats.get('intent_rate')} "
          f"severity MAE={stats.get('severity_mae')} disagreements={len(dis)} planted detected={planted_stats.get('flagged_rate')}")
    con.close()
    return report


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default="gemma4:e4b")
    ap.add_argument("--effort", default="none")
    ap.add_argument("--sample-size", type=int)
    ap.add_argument("--sample-rate", type=float, default=0.01)
    ap.add_argument("--max-sample", type=int, default=1500)
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--max-output-tokens", type=int, default=3000)
    ap.add_argument("--budget", type=float, default=0.5)
    return ap


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
