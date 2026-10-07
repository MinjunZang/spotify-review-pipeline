"""Stage 6 - Recommend (role: memo).

Code first turns saved calculations into claims with IDs:
  claims.csv        C### issue-level (contract metrics: complaint_count, severity_sum, mean_severity, priority_score)
  claims_extra.csv  A### product-area, T### trend, K### coverage numbers (explained separately in README)
The memo model receives only these claims, the top issues with a few quotes/review IDs, and limitations.
Code then checks every cited claim ID, issue ID, review ID and number; one retry with the problems listed;
the result and its check report are saved. A person still reads the argument.

Warm runs: if the evidence pack is unchanged the saved memo is reused (0 calls).
"""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from .common import now_iso, write_json
from .llm import RoleCaller
from .schema import prompt_hash, prompt_text

PROMPT = "memo_v2"  # v1 output (outputs/runs/*/memo history) did not address the #1 ranked issue
TOP_ISSUES = 10
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
CLAIM = re.compile(r"\[([CATK]\d{3})\]")
ISSUE = re.compile(r"`([a-z_]+\.[a-z_]+)`")
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%?)")


def build_claims(ranking, aggregates):
    issue_claims, extra = [], []
    n = 0
    for r in ranking[:TOP_ISSUES]:
        for metric in ("complaint_count", "severity_sum", "mean_severity", "priority_score"):
            n += 1
            issue_claims.append({"claim_id": f"C{n:03d}", "issue_id": r["issue_id"], "metric": metric, "value": str(r[metric])})
    a = 0
    for row in aggregates["areas"]:
        for metric in ("complaint_count", "severity_sum", "mean_severity", "share_of_complaints_pct",
                       "cancellation_count", "sev4plus_count", "sev4plus_share_of_area_pct"):
            if row[metric] is not None:
                a += 1
                extra.append({"claim_id": f"A{a:03d}", "subject": row["area"], "metric": metric, "value": str(row[metric])})
    t = 0
    for row in aggregates["trend"]:
        for metric in ("early_complaints", "early_completed_records", "early_share_pct",
                       "late_complaints", "late_completed_records", "late_share_pct"):
            if row[metric] is not None:
                t += 1
                extra.append({"claim_id": f"T{t:03d}", "subject": row["area"], "metric": metric, "value": str(row[metric])})
    cov = aggregates["coverage"]
    k = 0
    for metric, value in (("source_rows", cov["source_rows"]), ("completed_records", cov["completed_records"]),
                          ("quarantined_records", cov["status"].get("quarantined", 0)),
                          ("pending_records", cov["status"].get("pending", 0)),
                          ("complaint_or_cancellation_records", aggregates["complaint_or_cancellation_records"])):
        k += 1
        extra.append({"claim_id": f"K{k:03d}", "subject": "corpus", "metric": metric, "value": str(value)})
    return issue_claims, extra


def check_memo(text, claims, review_ids, issue_ids):
    """Return a list of problems: unknown claim/issue/review IDs, numbers not backed by an adjacent claim."""
    problems = []
    for cid in CLAIM.findall(text):
        if cid not in claims:
            problems.append(f"unknown claim id [{cid}]")
    for iid in ISSUE.findall(text):
        if iid not in issue_ids:
            problems.append(f"unknown issue id `{iid}`")
    for rid in UUID.findall(text):
        if rid not in review_ids:
            problems.append(f"review id not in evidence pack: {rid}")
    # blank out IDs and dates with same-length spaces so character positions stay aligned
    blank = lambda m: " " * len(m.group(0))  # noqa: E731
    scrub = UUID.sub(blank, text)
    scrub = re.sub(r"\b\d{4}-\d{2}(-\d{2})?\b", blank, scrub)
    scrub = re.sub(r"`[^`]*`", blank, scrub)
    cites = list(CLAIM.finditer(scrub))
    for m in NUMBER.finditer(scrub):
        if any(c.start() <= m.start() < c.end() for c in cites):
            continue  # the digits of a claim ID itself
        whole, frac, _ = m.groups()
        value = float(whole.replace(",", "") + (frac or ""))
        if not frac and value <= 10:
            continue  # small counting words like "top 3 issues"
        nxt = next((c for c in cites if c.start() >= m.end() and c.start() - m.end() <= 60), None)
        if nxt is None:
            problems.append(f"number without claim citation: {m.group(0)!r}")
            continue
        cid = nxt.group(1)
        if cid not in claims:
            continue  # already reported as unknown
        decimals = len(frac) - 1 if frac else 0
        try:
            backed = round(float(claims[cid]), decimals) == round(value, decimals)
        except ValueError:
            backed = False
        if not backed:
            problems.append(f"number {m.group(0)!r} does not match [{cid}] = {claims[cid]}")
    return problems


def run(args):
    run_dir = Path(args.run_dir)
    out = run_dir / "memo"
    out.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "ranking.csv", encoding="utf-8") as f:
        ranking = list(csv.DictReader(f))
    aggregates = json.loads((run_dir / "aggregates.json").read_text())
    issues = {i["issue_id"]: i for i in json.loads((run_dir / "group" / "issues.json").read_text())["issues"]}
    issue_claims, extra = build_claims(ranking, aggregates)
    for name, rows, cols in (("claims.csv", issue_claims, ["claim_id", "issue_id", "metric", "value"]),
                             ("claims_extra.csv", extra, ["claim_id", "subject", "metric", "value"])):
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    claims = {c["claim_id"]: c["value"] for c in issue_claims + extra}

    top = []
    for r in ranking[:TOP_ISSUES]:
        i = issues.get(r["issue_id"], {})
        top.append({"rank": int(r["rank"]), "issue_id": r["issue_id"], "name": i.get("name"),
                    "description": i.get("description"),
                    "claims": {c["metric"]: f'{c["value"]} [{c["claim_id"]}]' for c in issue_claims if c["issue_id"] == r["issue_id"]},
                    "examples": [{"review_id": e["review_id"], "severity": e["severity"], "quote": e["quote"][:160]}
                                 for e in i.get("examples", [])[:3]]})
    pack = {"ranking_rule": "priority_score = complaint_count x mean_severity = severity_sum; complaint and cancellation records only",
            "top_issues": top,
            "area_claims": [f'{c["claim_id"]}: {c["subject"]} {c["metric"]} = {c["value"]}' for c in extra if c["claim_id"][0] == "A"],
            "trend_claims": [f'{c["claim_id"]}: {c["subject"]} {c["metric"]} = {c["value"]}' for c in extra if c["claim_id"][0] == "T"],
            "coverage_claims": [f'{c["claim_id"]}: {c["metric"]} = {c["value"]}' for c in extra if c["claim_id"][0] == "K"],
            "trend_windows": "early = 2022-06..2022-11, late = 2023-05..2023-10 (full months only); share = area complaints / completed records",
            "limitations": aggregates["notes"]}
    cfg = f"{args.model}|effort={args.effort}|{PROMPT}@{prompt_hash(PROMPT)}"
    pack_hash = hashlib.sha256(json.dumps([pack, cfg], sort_keys=True).encode()).hexdigest()
    write_json(out / "memo_evidence_pack.json", {"pack_sha256": pack_hash, **pack})
    saved = out / "memo.json"
    if saved.exists() and json.loads(saved.read_text()).get("pack_sha256") == pack_hash:
        print("[memo] evidence pack unchanged -> reusing saved memo (0 calls)")
        return json.loads(saved.read_text())

    review_ids = {e["review_id"] for t in top for e in t["examples"]}
    caller = RoleCaller(run_dir, "memo", args.provider, args.model, args.effort, args.max_output_tokens, args.budget, cfg)
    schema = {"type": "object", "additionalProperties": False, "required": ["priority_area", "headline", "memo_markdown"],
              "properties": {"priority_area": {"type": "string", "enum": ["access", "usability", "playback", "billing_support"]},
                             "headline": {"type": "string"}, "memo_markdown": {"type": "string"}}}
    user = "Evidence pack:\n" + json.dumps(pack, ensure_ascii=False, indent=1)
    attempts = []
    result = None
    for attempt in range(2):
        parsed, res = caller.call(prompt_text(PROMPT), user, schema, "memo", [], inputs_note="memo/memo_evidence_pack.json")
        if not parsed or "memo_markdown" not in parsed:
            attempts.append({"attempt": attempt + 1, "problems": [res.error or "no structured memo returned"]})
            continue
        problems = check_memo(parsed["memo_markdown"] + "\n" + parsed["headline"], claims, review_ids, set(issues))
        attempts.append({"attempt": attempt + 1, "problems": problems})
        result = parsed
        if not problems:
            break
        user += "\n\nYour previous memo failed these code checks; fix them and keep all other rules:\n- " + "\n- ".join(problems[:30])
    if result is None:
        raise SystemExit("[memo] no valid memo after 2 attempts; see calls.jsonl")
    final_problems = attempts[-1]["problems"]
    record = {"generated_at": now_iso(), "pack_sha256": pack_hash, "memo_config": cfg, **result,
              "check": {"passed": not final_problems, "problems": final_problems, "attempts": attempts},
              "cited_claim_ids": sorted(set(CLAIM.findall(result["memo_markdown"]))),
              "cited_issue_ids": sorted(set(ISSUE.findall(result["memo_markdown"]))),
              "cited_review_ids": sorted(set(UUID.findall(result["memo_markdown"])))}
    write_json(saved, record)
    header = (f"# Decision memo: {result['headline']}\n\n*Generated by `{args.model}` from saved aggregates "
              f"({now_iso()}); every number cites a claim ID in `claims.csv` / `claims_extra.csv`. "
              f"Code check: {'passed' if not final_problems else 'FAILED - see memo.json'}.*\n\n")
    (out / "memo.md").write_text(header + result["memo_markdown"].strip() + "\n", encoding="utf-8")
    print(f"[memo] priority={result['priority_area']} check={'passed' if not final_problems else final_problems[:5]}")
    return record


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--max-output-tokens", type=int, default=3000)
    ap.add_argument("--budget", type=float, default=0.2)
    return ap


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
