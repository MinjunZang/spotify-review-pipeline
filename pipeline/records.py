"""Write the final per-source-ID records (contract format) from pipeline state.

Exactly one line per source review_id, in source order: completed (labels + label_config, and
cache_source_id for exact-text reuse) or quarantined (reason). Pending rows are written as
quarantined with reason 'unprocessed_pending' only when --finalize is given, so an unfinished run
is never silently presented as complete.

Outputs: <run_dir>/records.jsonl.gz, <run_dir>/quarantine.jsonl, <run_dir>/enriched.csv.gz (with source values)
"""

import argparse
import csv
import gzip
import io
import json
import sqlite3
from collections import Counter
from pathlib import Path

from .common import write_json

SQL = """
SELECT v.review_id, v.source_sha256, s.status, s.reason, s.attempts, s.label_config, s.cache_source_id,
       r.topic, r.subtopic, r.intent, r.sentiment, r.severity, r.entities, r.evidence_quote, r.needs_review,
       v.review_text, v.review_rating, v.review_likes, v.app_version, v.review_timestamp
FROM reviews v JOIN status s ON s.review_id=v.review_id
LEFT JOIN results r ON s.status='completed' AND r.label_config=s.label_config
     AND r.source_review_id=COALESCE(s.cache_source_id, s.review_id)
ORDER BY v.row_num
"""


def iter_records(con, finalize=False):
    for row in con.execute(SQL):
        (rid, src, status, reason, attempts, cfg, cache_src, topic, sub, intent, sent, sev, ents, quote, nr,
         text, rating, likes, ver, ts) = row
        source = {"review_rating": rating, "review_likes": likes, "app_version": ver, "review_timestamp": ts}
        if status == "completed":
            rec = {"review_id": rid, "source_sha256": src, "status": "completed", "topic": topic, "intent": intent,
                   "sentiment": sent, "severity": sev, "entities": json.loads(ents), "evidence_quote": quote,
                   "needs_review": bool(nr), "label_config": cfg, "subtopic": sub}
            if cache_src:
                rec["cache_source_id"] = cache_src
        elif status == "quarantined":
            rec = {"review_id": rid, "source_sha256": src, "status": "quarantined", "reason": reason,
                   "attempts": attempts}
        else:
            if not finalize:
                rec = {"review_id": rid, "source_sha256": src, "status": "pending", "attempts": attempts}
            else:
                rec = {"review_id": rid, "source_sha256": src, "status": "quarantined",
                       "reason": "unprocessed_pending" + (f": {reason}" if reason else ""), "attempts": attempts}
        yield rec, text, source


def write(db, run_dir, finalize=False):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    counts, reasons = Counter(), Counter()
    cols = ["review_id", "status", "topic", "subtopic", "intent", "severity", "sentiment", "needs_review",
            "evidence_quote", "entities", "cache_source_id", "reason", "review_rating", "review_likes",
            "app_version", "review_timestamp", "review_text", "source_sha256", "label_config"]
    with gzip.open(run_dir / "records.jsonl.gz", "wt", encoding="utf-8") as rf, \
            (run_dir / "quarantine.jsonl").open("w", encoding="utf-8") as qf, \
            gzip.open(run_dir / "enriched.csv.gz", "wt", encoding="utf-8", newline="") as ef:
        w = csv.DictWriter(ef, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for rec, text, source in iter_records(con, finalize):
            counts[rec["status"]] += 1
            rf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if rec["status"] == "quarantined":
                reasons[rec["reason"].split(":")[0]] += 1
                qf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            w.writerow({**rec, **source, "review_text": text,
                        "entities": json.dumps(rec.get("entities", [])) if rec["status"] == "completed" else ""})
    cache = con.execute("SELECT COUNT(*) FROM status WHERE status='completed' AND cache_source_id IS NOT NULL").fetchone()[0]
    summary = {"records": sum(counts.values()), "by_status": dict(counts), "quarantine_reasons": dict(reasons),
               "completed_via_exact_text_cache": cache, "finalized": finalize}
    write_json(run_dir / "records_summary.json", summary)
    con.close()
    print(f"[records] {summary}")
    return summary


def read_records(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--finalize", action="store_true")
    a = ap.parse_args(argv)
    return write(a.db, a.run_dir, a.finalize)


if __name__ == "__main__":
    main()
