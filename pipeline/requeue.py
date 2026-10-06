"""Requeue quarantined records for one more attempt after a code fix (logged, never silent).

Only records whose quarantine reason starts with one of --reasons are reset to pending; their attempt
counts are kept and the action is written to <run_dir>/run_log.jsonl with the affected IDs.

  python -m pipeline.requeue --db work/full/pipeline.sqlite --run-dir outputs/runs/full \
      --reasons malformed_output --note "parser now ignores trailing output after the first JSON object"
"""

import argparse
import sqlite3

from .common import append_jsonl, now_iso


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--reasons", required=True, help="comma-separated reason prefixes")
    ap.add_argument("--note", required=True)
    a = ap.parse_args(argv)
    con = sqlite3.connect(a.db)
    prefixes = [p.strip() for p in a.reasons.split(",") if p.strip()]
    if "empty_review_text" in prefixes:
        raise SystemExit("empty texts are never requeued")
    where = " OR ".join("reason LIKE ?" for _ in prefixes)
    ids = [r[0] for r in con.execute(f"SELECT review_id FROM status WHERE status='quarantined' AND ({where})",
                                     [p + "%" for p in prefixes])]
    with con:
        con.executemany("UPDATE status SET status='pending', reason='requeued: ' || reason WHERE review_id=?",
                        [(i,) for i in ids])
    append_jsonl(f"{a.run_dir}/run_log.jsonl", {"ts": now_iso(), "stage": "enrich", "event": "requeue",
                                                "reasons": prefixes, "note": a.note, "count": len(ids), "review_ids": ids})
    print(f"[requeue] {len(ids)} records reset to pending ({prefixes})")


if __name__ == "__main__":
    main()
