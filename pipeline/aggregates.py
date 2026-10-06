"""Aggregates for the memo and dashboard (code only).

Product areas answer the assignment question (access / usability / playback / billing+support), with
downloads, catalog and other shown separately. Trend: complaint share per area in comparable full-month
windows (first and last calendar months are partial and excluded), with denominators.
"""

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .common import now_iso, write_json
from .rank import mean6

AREA = {"access": "access", "usability": "usability", "playback": "playback", "billing": "billing_support",
        "support": "billing_support", "downloads": "downloads", "catalog": "catalog", "other": "other"}
EARLY = ["2022-06", "2022-07", "2022-08", "2022-09", "2022-10", "2022-11"]
LATE = ["2023-05", "2023-06", "2023-07", "2023-08", "2023-09", "2023-10"]

SQL = """
SELECT s.review_id, substr(v.review_timestamp,1,7), r.topic, r.intent, r.severity, r.needs_review
FROM status s JOIN reviews v ON v.review_id=s.review_id
JOIN results r ON r.source_review_id=COALESCE(s.cache_source_id, s.review_id) AND r.label_config=s.label_config
WHERE s.status='completed'
"""


def pct(a, b):
    return round(100 * a / b, 2) if b else None


def run(db, run_dir):
    run_dir = Path(run_dir)
    con = sqlite3.connect(db)
    status = dict(con.execute("SELECT status, COUNT(*) FROM status GROUP BY status").fetchall())
    rows = con.execute(SQL).fetchall()
    completed = len(rows)
    intents = Counter(r[3] for r in rows)
    comp = [r for r in rows if r[3] in ("complaint", "cancellation")]
    area = defaultdict(lambda: Counter())
    for _, month, topic, intent, sev, nr in rows:
        a = area[AREA[topic]]
        a["records"] += 1
        if intent in ("complaint", "cancellation"):
            a["complaints"] += 1
            a["severity_sum"] += sev
            a["cancellations"] += intent == "cancellation"
            a["blocked_or_harm_sev4plus"] += sev >= 4
    areas = []
    for name, a in area.items():
        areas.append({"area": name, "complaint_count": a["complaints"], "severity_sum": a["severity_sum"],
                      "mean_severity": mean6(a["severity_sum"], a["complaints"]) if a["complaints"] else None,
                      "share_of_complaints_pct": pct(a["complaints"], len(comp)),
                      "cancellation_count": a["cancellations"], "sev4plus_count": a["blocked_or_harm_sev4plus"],
                      "sev4plus_share_of_area_pct": pct(a["blocked_or_harm_sev4plus"], a["complaints"])})
    areas.sort(key=lambda x: (-x["severity_sum"], x["area"]))

    month_tot, month_area = Counter(), defaultdict(Counter)
    for _, month, topic, intent, sev, nr in rows:
        month_tot[month] += 1
        if intent in ("complaint", "cancellation"):
            month_area[AREA[topic]][month] += 1
    trend = []
    for name in sorted(month_area):
        e_n = sum(month_area[name][m] for m in EARLY)
        e_d = sum(month_tot[m] for m in EARLY)
        l_n = sum(month_area[name][m] for m in LATE)
        l_d = sum(month_tot[m] for m in LATE)
        trend.append({"area": name, "early_window": f"{EARLY[0]}..{EARLY[-1]}", "early_complaints": e_n,
                      "early_completed_records": e_d, "early_share_pct": pct(e_n, e_d),
                      "late_window": f"{LATE[0]}..{LATE[-1]}", "late_complaints": l_n,
                      "late_completed_records": l_d, "late_share_pct": pct(l_n, l_d)})
    monthly = {m: {"completed": month_tot[m], **{a: month_area[a][m] for a in month_area}} for m in sorted(month_tot)}
    result = {"generated_at": now_iso(),
              "coverage": {"source_rows": sum(status.values()), "status": status, "completed_records": completed},
              "intents": dict(intents), "complaint_or_cancellation_records": len(comp),
              "needs_review_records": sum(1 for r in rows if r[5]),
              "areas": areas, "trend": trend, "monthly": monthly,
              "notes": ["Self-selected public reviews; not a customer population.",
                        "Cancellation = expressed intent in text, not observed churn.",
                        "First (2022-05) and last (2023-11) months are partial and excluded from trend windows."]}
    write_json(run_dir / "aggregates.json", result)
    with (run_dir / "aggregates_areas.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(areas[0].keys()) if areas else ["area"])
        w.writeheader()
        w.writerows(areas)
    con.close()
    print(f"[aggregates] completed={completed} complaints={len(comp)} areas={[(a['area'], a['severity_sum']) for a in areas]}")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args(argv)
    return run(a.db, a.run_dir)


if __name__ == "__main__":
    main()
