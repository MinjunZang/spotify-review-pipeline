"""Stage 5 - Rank (code only; no model, no database).

Regenerates the baseline ranking from SAVED outputs only: records.jsonl(.gz) + membership.csv.
  complaint_count = membership count; severity_sum = sum of member severity;
  mean_severity = severity_sum / complaint_count (6 decimals, half-up); priority_score = severity_sum.
  Order: priority_score desc, then issue_id asc. Ranks start at 1.

Usage (grader-friendly, no API key):
  python -m pipeline.rank --records grading/records.jsonl.gz --membership grading/membership.csv --out ranking.csv
"""

import argparse
import csv
import sys
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .records import read_records

COLUMNS = ["rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"]


def mean6(total, n):
    return str((Decimal(total) / Decimal(n)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def compute(records_path, membership_path):
    sev = {}
    for r in read_records(records_path):
        if r.get("status") == "completed" and r.get("intent") in ("complaint", "cancellation"):
            sev[r["review_id"]] = r["severity"]
    members, seen = defaultdict(list), set()
    with open(membership_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pair = (row["issue_id"], row["review_id"])
            if pair in seen:
                raise ValueError(f"duplicate membership {pair}")
            if row["review_id"] not in sev:
                raise ValueError(f"membership references a non-complaint or unknown record: {row['review_id']}")
            seen.add(pair)
            members[row["issue_id"]].append(sev[row["review_id"]])
    grouped = {rid for _, rid in seen}
    if set(sev) - grouped:
        raise ValueError(f"{len(set(sev) - grouped)} complaint/cancellation records are not in any issue")
    rows = [{"issue_id": iid, "complaint_count": len(v), "severity_sum": sum(v),
             "mean_severity": mean6(sum(v), len(v)), "priority_score": sum(v)} for iid, v in members.items()]
    rows.sort(key=lambda x: (-x["priority_score"], x["issue_id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def write(rows, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: str(r[k]) for k in COLUMNS})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", required=True)
    ap.add_argument("--membership", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rows = compute(a.records, a.membership)
    write(rows, a.out)
    for r in rows[:10]:
        print(f"{r['rank']:>3}  {r['issue_id']:<40} n={r['complaint_count']:<7} mean={r['mean_severity']}  score={r['priority_score']}")
    print(f"[rank] {len(rows)} issues -> {a.out}", file=sys.stderr)
    return rows


if __name__ == "__main__":
    main()
