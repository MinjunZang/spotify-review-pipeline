"""Load saved pipeline outputs into Postgres for the deployed dashboard (no model calls).

Reads only saved artifacts: records + enriched values (records.jsonl.gz / enriched.csv.gz), membership.csv,
ranking.csv, issues.json, aggregates.json, memo/memo.json + claims, verify report, cost report inputs.

  .venv/bin/python dashboard/load_db.py --run-dir outputs/runs/full          # DATABASE_URL from .env
"""

import argparse
import csv
import gzip
import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.llm import load_env  # noqa: E402

SCHEMA = """
DROP TABLE IF EXISTS reviews, issues, issue_examples, areas, trend, monthly, claims, memo, meta CASCADE;
CREATE TABLE meta (key TEXT PRIMARY KEY, value JSONB NOT NULL);
CREATE TABLE areas (area TEXT PRIMARY KEY, complaint_count INT, severity_sum INT, mean_severity NUMERIC,
  share_of_complaints_pct NUMERIC, cancellation_count INT, sev4plus_count INT, sev4plus_share_of_area_pct NUMERIC);
CREATE TABLE trend (area TEXT PRIMARY KEY, early_window TEXT, early_complaints INT, early_completed_records INT,
  early_share_pct NUMERIC, late_window TEXT, late_complaints INT, late_completed_records INT, late_share_pct NUMERIC);
CREATE TABLE monthly (month TEXT, area TEXT, complaints INT, completed INT, PRIMARY KEY (month, area));
CREATE TABLE issues (rank INT, issue_id TEXT PRIMARY KEY, topic TEXT, name TEXT, description TEXT,
  complaint_count INT, severity_sum INT, mean_severity TEXT, priority_score INT, cancellation_count INT,
  name_source TEXT);
CREATE TABLE issue_examples (issue_id TEXT, review_id TEXT, severity INT, quote TEXT);
CREATE TABLE claims (claim_id TEXT PRIMARY KEY, kind TEXT, subject TEXT, metric TEXT, value TEXT);
CREATE TABLE memo (id INT PRIMARY KEY, priority_area TEXT, headline TEXT, markdown TEXT, model_config TEXT,
  check_passed BOOLEAN, check_problems JSONB, generated_at TEXT, cited_claim_ids JSONB, cited_issue_ids JSONB,
  cited_review_ids JSONB);
CREATE TABLE reviews (review_id TEXT PRIMARY KEY, status TEXT, reason TEXT, topic TEXT, subtopic TEXT, intent TEXT,
  severity INT, sentiment REAL, needs_review BOOLEAN, evidence_quote TEXT, cache_source_id TEXT, issue_id TEXT,
  review_rating TEXT, review_timestamp TEXT, app_version TEXT);
"""
INDEXES = """
CREATE INDEX reviews_issue ON reviews(issue_id, severity DESC);
CREATE INDEX reviews_status ON reviews(status);
CREATE INDEX reviews_topic_intent ON reviews(topic, intent);
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    load_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set in .env")
    run = Path(a.run_dir)
    ranking = list(csv.DictReader(open(run / "ranking.csv", encoding="utf-8")))
    issues = {i["issue_id"]: i for i in json.loads((run / "group" / "issues.json").read_text())["issues"]}
    agg = json.loads((run / "aggregates.json").read_text())
    memo = json.loads((run / "memo" / "memo.json").read_text())
    membership = {}
    for row in csv.DictReader(open(run / "group" / "membership.csv", encoding="utf-8")):
        membership[row["review_id"]] = row["issue_id"]

    with psycopg.connect(url) as con, con.cursor() as cur:
        cur.execute(SCHEMA)
        meta = {
            "coverage": agg["coverage"], "intents": agg["intents"],
            "complaint_or_cancellation_records": agg["complaint_or_cancellation_records"],
            "needs_review_records": agg["needs_review_records"], "notes": agg["notes"],
            "records_summary": json.loads((run / "records_summary.json").read_text()),
            "run_manifest": json.loads((run / "run_manifest.json").read_text()),
            "ingestion": json.loads((run / "ingestion" / "ingestion_report.json").read_text())["counts"],
        }
        for extra, path in (("verify", run / "verify" / "verify_report.json"),
                            ("golden", ROOT / "evals" / "golden" / "full_run" / "summary.json"),
                            ("run_summary", run / "run_summary.json")):
            if path.exists():
                v = json.loads(path.read_text())
                if extra == "verify":
                    v.pop("planted_error_test", None)
                meta[extra] = v
        for k, v in meta.items():
            cur.execute("INSERT INTO meta VALUES (%s, %s)", (k, json.dumps(v)))
        for r in agg["areas"]:
            cur.execute("INSERT INTO areas VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (r["area"], r["complaint_count"], r["severity_sum"], r["mean_severity"], r["share_of_complaints_pct"],
                         r["cancellation_count"], r["sev4plus_count"], r["sev4plus_share_of_area_pct"]))
        for r in agg["trend"]:
            cur.execute("INSERT INTO trend VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (r["area"], r["early_window"], r["early_complaints"], r["early_completed_records"], r["early_share_pct"],
                         r["late_window"], r["late_complaints"], r["late_completed_records"], r["late_share_pct"]))
        for month, vals in agg["monthly"].items():
            for area, n in vals.items():
                if area != "completed":
                    cur.execute("INSERT INTO monthly VALUES (%s,%s,%s,%s)", (month, area, n, vals["completed"]))
        cancels = {}
        with gzip.open(run / "records.jsonl.gz", "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("intent") == "cancellation" and r["review_id"] in membership:
                    cancels[membership[r["review_id"]]] = cancels.get(membership[r["review_id"]], 0) + 1
        for r in ranking:
            i = issues.get(r["issue_id"], {})
            cur.execute("INSERT INTO issues VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (int(r["rank"]), r["issue_id"], r["issue_id"].split(".")[0], i.get("name"), i.get("description"),
                         int(r["complaint_count"]), int(r["severity_sum"]), r["mean_severity"], int(r["priority_score"]),
                         cancels.get(r["issue_id"], 0), i.get("name_source")))
            for e in i.get("examples", []):
                cur.execute("INSERT INTO issue_examples VALUES (%s,%s,%s,%s)",
                            (r["issue_id"], e["review_id"], e["severity"], e["quote"]))
        for name, kind in (("claims.csv", "issue"), ("claims_extra.csv", None)):
            for c in csv.DictReader(open(run / "memo" / name, encoding="utf-8")):
                cur.execute("INSERT INTO claims VALUES (%s,%s,%s,%s,%s)",
                            (c["claim_id"], kind or {"A": "area", "T": "trend", "K": "coverage"}[c["claim_id"][0]],
                             c.get("issue_id") or c.get("subject"), c["metric"], c["value"]))
        cur.execute("INSERT INTO memo VALUES (1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (memo["priority_area"], memo["headline"], memo["memo_markdown"], memo["memo_config"],
                     memo["check"]["passed"], json.dumps(memo["check"]["problems"]), memo["generated_at"],
                     json.dumps(memo["cited_claim_ids"]), json.dumps(memo["cited_issue_ids"]),
                     json.dumps(memo["cited_review_ids"])))
        print("[load] summary tables loaded; streaming review records...")
        n = 0
        with gzip.open(run / "enriched.csv.gz", "rt", encoding="utf-8", newline="") as f, \
                cur.copy("COPY reviews FROM STDIN") as cp:
            for r in csv.DictReader(f):
                done = r["status"] == "completed"
                cp.write_row((r["review_id"], r["status"], r["reason"] or None, r["topic"] or None, r["subtopic"] or None,
                              r["intent"] or None, int(r["severity"]) if done else None,
                              float(r["sentiment"]) if done else None,
                              (r["needs_review"] == "True") if done else None,
                              r["evidence_quote"][:500] if done else None, r["cache_source_id"] or None,
                              membership.get(r["review_id"]), r["review_rating"], r["review_timestamp"],
                              r["app_version"] or None))
                n += 1
        cur.execute(INDEXES)
        con.commit()
        print(f"[load] {n} review rows loaded")


if __name__ == "__main__":
    main()
