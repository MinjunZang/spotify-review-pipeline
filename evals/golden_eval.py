"""Golden-set evaluation: enricher predictions vs the human-reviewed golden 50.

The enricher sees ONLY review_text (data/golden_50_to_label.csv has blank label columns; human answers in
evals/golden/golden_50_human.csv are never model inputs). Predictions come from a pipeline DB:
  --db work/golden_eval/pipeline.sqlite   (pre-run check: enrich the 50 texts on their own)
  --db work/full/pipeline.sqlite          (final check: the labels actually exported in the full run)

Metrics (declared in advance): topic & intent agreement (strict, and allowing the human's listed
alternatives for ambiguous cases), severity exact agreement + MAE, sentiment MAE and agreement within
|diff| <= 0.5, quote = exact substring (code) + overlap with the human quote, entities = unsupported
additions, needs_review as a prediction (precision/recall vs the human flag). Writes evals/golden/<tag>/.

  python3 evals/golden_eval.py --run-enrich      # enrich the 50 texts (tiny paid call), then evaluate
  python3 evals/golden_eval.py --db work/full/pipeline.sqlite --tag full_run
"""

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.common import TOPICS, INTENTS, now_iso, write_json  # noqa: E402

HUMAN = ROOT / "evals" / "golden" / "golden_50_human.csv"
INPUT = ROOT / "data" / "golden_50_to_label.csv"
SENT_TOL = 0.5


def predictions(db, ids):
    con = sqlite3.connect(db)
    q = f"""SELECT s.review_id, s.status, s.reason, r.topic, r.subtopic, r.intent, r.severity, r.sentiment,
                   r.evidence_quote, r.entities, r.needs_review, s.label_config
            FROM status s LEFT JOIN results r ON r.source_review_id=COALESCE(s.cache_source_id, s.review_id)
                 AND r.label_config=s.label_config
            WHERE s.review_id IN ({','.join('?' * len(ids))})"""
    out = {}
    for row in con.execute(q, ids):
        out[row[0]] = dict(zip(("review_id", "status", "reason", "topic", "subtopic", "intent", "severity", "sentiment",
                                "evidence_quote", "entities", "needs_review", "label_config"), row))
    con.close()
    return out


def overlap(a, b):
    a, b = set(a.lower().split()), set(b.lower().split())
    return round(len(a & b) / len(a | b), 2) if a | b else 0.0


def evaluate(db, tag):
    human = [r for r in csv.DictReader(HUMAN.open(encoding="utf-8")) if r["topic"]]
    preds = predictions(db, [h["review_id"] for h in human])
    cases, conf = [], defaultdict(Counter)
    tot = Counter()
    for h in human:
        p = preds.get(h["review_id"], {})
        ok = p.get("status") == "completed"
        alt_t = [h["topic"]] + [x for x in h["alt_topics"].split("|") if x]
        alt_i = [h["intent"]] + [x for x in h["alt_intents"].split("|") if x]
        alt_s = [int(h["severity"])] + [int(x) for x in h["alt_severities"].split("|") if x]
        c = {"review_id": h["review_id"], "text": h["review_text"], "label_source": h["label_source"],
             "ambiguous": h["ambiguous"] == "true", "status": p.get("status", "missing"),
             "human": {"topic": h["topic"], "intent": h["intent"], "severity": int(h["severity"]),
                       "sentiment": float(h["sentiment"]), "needs_review": h["needs_review"] == "true",
                       "quote": h["evidence_quote"], "alternatives": {"topic": alt_t[1:], "intent": alt_i[1:], "severity": alt_s[1:]}}}
        if ok:
            ents = json.loads(p["entities"])
            c["model"] = {"topic": p["topic"], "subtopic": p["subtopic"], "intent": p["intent"], "severity": p["severity"],
                          "sentiment": p["sentiment"], "needs_review": bool(p["needs_review"]), "quote": p["evidence_quote"],
                          "entities": ents}
            c.update({"topic_strict": p["topic"] == h["topic"], "topic_accepted": p["topic"] in alt_t,
                      "intent_strict": p["intent"] == h["intent"], "intent_accepted": p["intent"] in alt_i,
                      "severity_exact": p["severity"] == int(h["severity"]), "severity_accepted": p["severity"] in alt_s,
                      "severity_abs_err": abs(p["severity"] - int(h["severity"])),
                      "sentiment_abs_err": round(abs(p["sentiment"] - float(h["sentiment"])), 2),
                      "quote_is_substring": p["evidence_quote"] in h["review_text"],
                      "quote_overlap_with_human": overlap(p["evidence_quote"], h["evidence_quote"]),
                      "unsupported_entities": [e for e in ents if e.split()[0] not in h["review_text"].lower()]})
            c["sentiment_within_tol"] = c["sentiment_abs_err"] <= SENT_TOL
            for k in ("topic_strict", "topic_accepted", "intent_strict", "intent_accepted", "severity_exact",
                      "severity_accepted", "sentiment_within_tol", "quote_is_substring"):
                tot[k] += c[k]
            tot["severity_abs_err"] += c["severity_abs_err"]
            tot["sentiment_abs_err"] += c["sentiment_abs_err"]
            tot["unsupported_entities"] += len(c["unsupported_entities"])
            nr_h, nr_m = c["human"]["needs_review"], c["model"]["needs_review"]
            tot["nr_tp"] += nr_h and nr_m
            tot["nr_fp"] += nr_m and not nr_h
            tot["nr_fn"] += nr_h and not nr_m
            conf[h["topic"]][p["topic"]] += 1
        else:
            conf[h["topic"]]["<missing>"] += 1
        c["any_disagreement"] = not (ok and c["topic_strict"] and c["intent_strict"] and c["severity_exact"])
        cases.append(c)
    n = len(human)
    valid = sum(c["status"] == "completed" for c in cases)
    rate = lambda k: round(tot[k] / n, 4)  # noqa: E731  (missing predictions count as wrong)
    summary = {
        "generated_at": now_iso(), "tag": tag, "db": str(Path(db).relative_to(ROOT)), "cases": n, "valid_predictions": valid,
        "label_config": next((p["label_config"] for p in preds.values() if p.get("label_config")), None),
        "human_label_provenance": dict(Counter(c["label_source"] for c in cases)),
        "ambiguous_cases": sum(c["ambiguous"] for c in cases),
        "topic_agreement": {"strict": rate("topic_strict"), "accepting_human_alternatives": rate("topic_accepted")},
        "intent_agreement": {"strict": rate("intent_strict"), "accepting_human_alternatives": rate("intent_accepted")},
        "severity": {"exact": rate("severity_exact"), "accepting_alternatives": rate("severity_accepted"),
                     "mae": round(tot["severity_abs_err"] / valid, 3) if valid else None},
        "sentiment": {"tolerance": SENT_TOL, "within_tolerance": rate("sentiment_within_tol"),
                      "mae": round(tot["sentiment_abs_err"] / valid, 3) if valid else None},
        "evidence_quote": {"exact_substring": rate("quote_is_substring"),
                           "note": "Support is inspected manually in error_analysis.md; overlap with human quote is per case."},
        "entities": {"unsupported_additions": tot["unsupported_entities"],
                     "note": "Entities are extracted by code from a fixed term list, so additions are matched terms."},
        "needs_review_as_prediction": {"human_flagged": tot["nr_tp"] + tot["nr_fn"], "model_flagged": tot["nr_tp"] + tot["nr_fp"],
                                       "precision": round(tot["nr_tp"] / (tot["nr_tp"] + tot["nr_fp"]), 3) if tot["nr_tp"] + tot["nr_fp"] else None,
                                       "recall": round(tot["nr_tp"] / (tot["nr_tp"] + tot["nr_fn"]), 3) if tot["nr_tp"] + tot["nr_fn"] else None},
        "per_topic_counts_human": dict(Counter(c["human"]["topic"] for c in cases)),
        "confusion_topic_human_rows_model_cols": {k: dict(v) for k, v in conf.items()},
        "disagreements": sum(c["any_disagreement"] for c in cases),
        "note": "50 cases are a small diagnostic sample, not a population accuracy estimate.",
    }
    out = ROOT / "evals" / "golden" / tag
    write_json(out / "summary.json", summary)
    write_json(out / "cases.json", cases)
    with (out / "per_case.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["review_id", "label_source", "ambiguous", "human_topic", "model_topic", "human_intent", "model_intent",
                    "human_sev", "model_sev", "human_sent", "model_sent", "topic_ok", "intent_ok", "sev_ok", "text"])
        for c in cases:
            m = c.get("model", {})
            w.writerow([c["review_id"], c["label_source"], c["ambiguous"], c["human"]["topic"], m.get("topic"),
                        c["human"]["intent"], m.get("intent"), c["human"]["severity"], m.get("severity"),
                        c["human"]["sentiment"], m.get("sentiment"), c.get("topic_strict"), c.get("intent_strict"),
                        c.get("severity_exact"), c["text"][:200]])
    topics = [t for t in TOPICS if t in conf or any(t in v for v in conf.values())] + (["<missing>"] if any("<missing>" in v for v in conf.values()) else [])
    md = [f"# Golden-set comparison ({tag})\n", f"Predictions: `{summary['label_config']}` · human labels: {summary['human_label_provenance']}\n",
          "| metric | value |", "|---|---|",
          f"| topic agreement (strict / with human alternatives) | {summary['topic_agreement']['strict']:.0%} / {summary['topic_agreement']['accepting_human_alternatives']:.0%} |",
          f"| intent agreement (strict / with alternatives) | {summary['intent_agreement']['strict']:.0%} / {summary['intent_agreement']['accepting_human_alternatives']:.0%} |",
          f"| severity exact / with alternatives / MAE | {summary['severity']['exact']:.0%} / {summary['severity']['accepting_alternatives']:.0%} / {summary['severity']['mae']} |",
          f"| sentiment within ±{SENT_TOL} / MAE | {summary['sentiment']['within_tolerance']:.0%} / {summary['sentiment']['mae']} |",
          f"| quote exact substring | {summary['evidence_quote']['exact_substring']:.0%} |",
          f"| needs_review precision / recall | {summary['needs_review_as_prediction']['precision']} / {summary['needs_review_as_prediction']['recall']} |",
          f"| ambiguous cases (human) | {summary['ambiguous_cases']} |", f"| valid predictions | {valid}/{n} |\n",
          "## Topic confusion (rows = human, columns = model)\n",
          "| human \\ model | " + " | ".join(topics) + " |", "|---" * (len(topics) + 1) + "|"]
    for t in topics:
        if t in conf:
            md.append(f"| **{t}** | " + " | ".join(str(conf[t].get(x, "")) for x in topics) + " |")
    md.append("\n## Disagreements (topic, intent or severity differs)\n")
    md.append("| # | review (abridged) | human | model | source | human alternatives |")
    md.append("|---|---|---|---|---|---|")
    for i, c in enumerate(cases, 1):
        if c["any_disagreement"]:
            m = c.get("model")
            hm = f"{c['human']['topic']}/{c['human']['intent']}/{c['human']['severity']}"
            mm = f"{m['topic']}/{m['intent']}/{m['severity']}" if m else c["status"]
            alts = "; ".join(f"{k}: {','.join(map(str, v))}" for k, v in c["human"]["alternatives"].items() if v)
            md.append(f"| {i} | {c['text'][:70].replace('|', '/').replace(chr(10), ' ')} | {hm} | {mm} | {c['label_source']} | {alts} |")
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:14]))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-enrich", action="store_true", help="enrich the 50 golden texts in an isolated DB first (paid, tiny)")
    ap.add_argument("--db", default=str(ROOT / "work" / "golden_eval" / "pipeline.sqlite"))
    ap.add_argument("--tag", default="pre_full_run")
    a = ap.parse_args()
    if a.run_enrich:
        db = Path(a.db)
        if not db.exists():
            subprocess.run([sys.executable, "-m", "pipeline.ingest", "--input", str(INPUT), "--db", str(db),
                            "--out", str(db.parent / "ingestion")], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-m", "pipeline.enrich", "--db", str(db), "--run-dir",
                        str(ROOT / "evals" / "golden" / a.tag / "run"), "--budget", "0.05"], cwd=ROOT, check=True)
    evaluate(a.db, a.tag)


if __name__ == "__main__":
    main()
