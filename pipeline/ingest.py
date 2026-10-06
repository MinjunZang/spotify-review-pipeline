"""Stage 1 - Prepare (code only, no model).

Reads every row of the input CSV, preserves source values and IDs, computes the
grader's source row hash, profiles quality, finds exact duplicate texts, quarantines
empty texts and queues pending work in a local SQLite database.

Outputs:
  work/pipeline.sqlite                     reviews + record status (local state)
  outputs/ingestion/ingestion_report.json  our profile + reconciliation with manifest
  outputs/ingestion/ingestion.json         checker-format profile (copied to grading/)
  outputs/ingestion/data_manifest.json     source identity
  outputs/ingestion/quarantine_empty.jsonl the empty-text quarantines

Usage: python -m pipeline.ingest [--input path.csv] [--db work/pipeline.sqlite]
"""

import argparse
import sqlite3
import statistics
import time
from collections import Counter
from pathlib import Path

from .common import (DEFAULT_INPUT, EXPECTED_SHA256, OUTPUTS, WORK, append_jsonl,
                     is_empty, now_iso, read_rows, row_sha, text_sha, write_json)
from check_submission import profile as checker_profile  # noqa: E402 (path set by .common)

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
  row_num INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL UNIQUE,
  review_text TEXT NOT NULL, review_rating TEXT NOT NULL, review_likes TEXT NOT NULL,
  app_version TEXT NOT NULL, review_timestamp TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  is_empty INTEGER NOT NULL,
  canonical_id TEXT            -- first review_id with identical nonempty text (itself if first)
);
CREATE INDEX IF NOT EXISTS idx_reviews_text ON reviews(text_sha256);
CREATE TABLE IF NOT EXISTS status (
  review_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('pending','completed','quarantined')),
  reason TEXT, attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT
);
"""


def ingest(input_path, db_path, out_dir):
    t0 = time.time()
    input_path, db_path, out_dir = Path(input_path), Path(db_path), Path(out_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()  # ingestion is deterministic; rebuild from source each time
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    seen_ids, first_by_text = set(), {}
    dup_ids, empty_ids = [], []
    months, ratings, lengths = Counter(), Counter(), []
    missing_version = 0
    rows = 0
    batch = []
    for row in read_rows(input_path):
        rows += 1
        rid = row["review_id"]
        if rid in seen_ids:
            dup_ids.append(rid)
        seen_ids.add(rid)
        text = row["review_text"]
        empty = is_empty(text)
        tsha = text_sha(text)
        canonical_id = None
        if empty:
            empty_ids.append(rid)
        else:
            canonical_id = first_by_text.setdefault(tsha, rid)
            lengths.append(len(text))
        missing_version += not row["app_version"].strip()
        months[row["review_timestamp"][:7]] += 1
        ratings[row["review_rating"]] += 1
        batch.append((rows, rid, text, row["review_rating"], row["review_likes"], row["app_version"],
                      row["review_timestamp"], row_sha(row), tsha, int(empty), canonical_id))
        if len(batch) >= 20000:
            con.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
            batch.clear()
    con.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)

    ts = now_iso()
    con.execute("INSERT INTO status SELECT review_id, CASE is_empty WHEN 1 THEN 'quarantined' ELSE 'pending' END, "
                "CASE is_empty WHEN 1 THEN 'empty_review_text' END, 0, ? FROM reviews", (ts,))
    con.commit()

    nonempty = rows - len(empty_ids)
    distinct = len(first_by_text)
    dup_rows = nonempty - distinct
    top_dups = con.execute(
        "SELECT review_text, COUNT(*) c FROM reviews WHERE is_empty=0 GROUP BY text_sha256 "
        "ORDER BY c DESC, MIN(row_num) LIMIT 15").fetchall()

    q_path = out_dir / "quarantine_empty.jsonl"
    q_path.unlink(missing_ok=True)
    for rid, src in con.execute("SELECT review_id, source_sha256 FROM reviews WHERE is_empty=1 ORDER BY row_num"):
        append_jsonl(q_path, {"review_id": rid, "source_sha256": src, "status": "quarantined",
                              "reason": "empty_review_text", "attempts": 0})

    print("Running checker-format profile (second full read)...")
    grading_profile = checker_profile(input_path)
    write_json(out_dir / "ingestion.json", grading_profile)

    fsha = grading_profile["file_sha256"]
    lengths.sort()
    report = {
        "generated_at": ts,
        "input": {"path": input_path.name, "bytes": input_path.stat().st_size, "sha256": fsha,
                  "matches_course_manifest": fsha == EXPECTED_SHA256},
        "counts": {
            "source_rows": rows,
            "unique_review_ids": len(seen_ids),
            "duplicate_review_ids": len(dup_ids),
            "empty_review_text_quarantined": len(empty_ids),
            "nonempty_to_classify": nonempty,
            "distinct_nonempty_texts": distinct,
            "exact_duplicate_text_rows_reusable": dup_rows,
            "missing_app_version": missing_version,
        },
        "accounting_check": {
            "rows == nonempty + quarantined": rows == nonempty + len(empty_ids),
            "every_id_has_status": con.execute("SELECT COUNT(*) FROM status").fetchone()[0] == rows,
        },
        "empty_review_ids": empty_ids,
        "reviews_by_month": dict(sorted(months.items())),
        "reviews_by_rating": dict(sorted(ratings.items())),
        "first_review": grading_profile["first_review"],
        "last_review": grading_profile["last_review"],
        "partial_months_note": "First (2022-05, from 05-17) and last (2023-11, to 11-15) months are partial.",
        "text_length_chars": {"min": lengths[0], "median": statistics.median(lengths),
                              "p90": lengths[int(len(lengths) * .9)], "p99": lengths[int(len(lengths) * .99)],
                              "max": lengths[-1], "mean": round(sum(lengths) / len(lengths), 2)},
        "most_repeated_texts": [{"text": t[:80], "rows": c} for t, c in top_dups],
        "status_after_ingestion": dict(con.execute("SELECT status, COUNT(*) FROM status GROUP BY status").fetchall()),
        "runtime_seconds": round(time.time() - t0, 1),
    }
    write_json(out_dir / "ingestion_report.json", report)
    write_json(out_dir / "data_manifest.json", {
        "source_file": input_path.name, "bytes": report["input"]["bytes"], "sha256": fsha,
        "parsed_rows_sha256": grading_profile["parsed_rows_sha256"],
        "dataset_source": "https://drive.google.com/file/d/1P0rUoAS_wVjp3BYKqXMEyD4u0uJP1Bvf/view",
        "upstream": "https://www.kaggle.com/datasets/bwandowando/3-4-million-spotify-google-store-reviews (v2, CC0)",
        "hash_convention": "source_sha256 = SHA-256 of compact UTF-8 JSON of the six field strings (check_submission.row_sha)",
        "db": str(db_path.relative_to(db_path.parent.parent)),
    })
    con.close()
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--db", default=str(WORK / "pipeline.sqlite"))
    ap.add_argument("--out", default=str(OUTPUTS / "ingestion"))
    a = ap.parse_args()
    r = ingest(a.input, a.db, a.out)
    print({k: r[k] for k in ("input", "counts", "accounting_check", "runtime_seconds")})


if __name__ == "__main__":
    main()
