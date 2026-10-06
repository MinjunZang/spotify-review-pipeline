"""Stage 4 - Group (role: group).

Code assigns membership deterministically: every completed complaint/cancellation record joins exactly
one issue, issue_id = "<topic>.<subtopic>" from its validated enrichment labels (allow_multi_issue=false).
The model's bounded job: read a small evidence pack (counts + a few example quotes with IDs per issue)
and propose a human-readable name/description, flagging examples that don't fit. It cannot change
membership; code validates every ID it returns. The accepted mapping is saved so ranking needs no model.

Warm runs: if the evidence pack is unchanged (same hash) the saved names are reused - zero calls.
"""

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from .common import now_iso, write_json
from .llm import RoleCaller
from .schema import prompt_hash, prompt_text

PROMPT = "group_v1"
EXAMPLES_PER_ISSUE = 6

RECORDS_SQL = """
SELECT s.review_id, r.topic, r.subtopic, r.intent, r.severity, r.evidence_quote, v.row_num
FROM status s JOIN reviews v ON v.review_id=s.review_id
JOIN results r ON r.source_review_id=COALESCE(s.cache_source_id, s.review_id) AND r.label_config=s.label_config
WHERE s.status='completed'
"""


def completed_records(con):
    return [dict(zip(("review_id", "topic", "subtopic", "intent", "severity", "quote", "row_num"), r))
            for r in con.execute(RECORDS_SQL)]


def build_membership(records):
    members = {}
    for r in records:
        if r["intent"] in ("complaint", "cancellation"):
            members.setdefault(f"{r['topic']}.{r['subtopic']}", []).append(r)
    return members


def evidence_pack(members):
    """Bounded, deterministic examples: highest severity first, then a stable hash order; distinct quotes."""
    pack = []
    for iid in sorted(members):
        rs = sorted(members[iid], key=lambda r: (-r["severity"], hashlib.sha256(r["review_id"].encode()).hexdigest()))
        seen, ex = set(), []
        for r in rs:
            q = r["quote"][:200]
            if q.lower() in seen:
                continue
            seen.add(q.lower())
            ex.append({"review_id": r["review_id"], "severity": r["severity"], "quote": q})
            if len(ex) >= EXAMPLES_PER_ISSUE:
                break
        pack.append({"issue_id": iid, "members": len(members[iid]), "examples": ex})
    return pack


def group_schema(issue_ids):
    item = {"type": "object", "additionalProperties": False, "required": ["issue_id", "name", "description", "off_topic_ids"],
            "properties": {"issue_id": {"type": "string", "enum": issue_ids}, "name": {"type": "string"},
                           "description": {"type": "string"},
                           "off_topic_ids": {"type": "array", "items": {"type": "string"}}}}
    return {"type": "object", "additionalProperties": False, "required": ["issues"],
            "properties": {"issues": {"type": "array", "items": item}}}


def run(args):
    run_dir = Path(args.run_dir)
    out = run_dir / "group"
    out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(args.db)
    members = build_membership(completed_records(con))
    with (out / "membership.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["issue_id", "review_id"])
        for iid in sorted(members):
            for r in sorted(members[iid], key=lambda r: r["row_num"]):
                w.writerow([iid, r["review_id"]])
    pack = evidence_pack(members)
    cfg = f"{args.model}|effort={args.effort}|{PROMPT}@{prompt_hash(PROMPT)}"
    pack_hash = hashlib.sha256(json.dumps([pack, cfg], sort_keys=True).encode()).hexdigest()
    write_json(out / "evidence_pack.json", {"pack_sha256": pack_hash, "issues": pack})

    issues_path = out / "issues.json"
    if issues_path.exists() and json.loads(issues_path.read_text()).get("pack_sha256") == pack_hash:
        print("[group] evidence pack unchanged -> reusing saved issue names (0 calls)")
        return json.loads(issues_path.read_text())

    names = {}
    if pack:
        caller = RoleCaller(run_dir, "group", args.provider, args.model, args.effort, args.max_output_tokens,
                            args.budget, cfg)
        user = "Name these complaint issues:\n" + json.dumps(pack, ensure_ascii=False)
        ids_in_pack = {e["review_id"] for p in pack for e in p["examples"]}
        parsed, res = caller.call(prompt_text(PROMPT), user, group_schema([p["issue_id"] for p in pack]),
                                  "group_names", [], inputs_note="group/evidence_pack.json")
        for it in (parsed or {}).get("issues", []):
            if it.get("issue_id") in members and it["issue_id"] not in names:
                bad = [x for x in it.get("off_topic_ids", []) if x not in ids_in_pack]
                names[it["issue_id"]] = {"name": it["name"][:80], "description": it["description"][:300],
                                         "off_topic_ids": [x for x in it.get("off_topic_ids", []) if x in ids_in_pack],
                                         "rejected_ids": bad}
    issues = []
    for p in pack:
        n = names.get(p["issue_id"])
        issues.append({"issue_id": p["issue_id"], "members": p["members"],
                       "name": n["name"] if n else p["issue_id"].replace(".", ": ").replace("_", " "),
                       "description": n["description"] if n else "",
                       "name_source": "model" if n else "code_fallback",
                       "off_topic_example_ids": n["off_topic_ids"] if n else [],
                       "rejected_model_ids": n["rejected_ids"] if n else [],
                       "examples": p["examples"]})
    result = {"generated_at": now_iso(), "pack_sha256": pack_hash, "group_config": cfg,
              "membership_rule": "one issue per complaint/cancellation record: issue_id = topic.subtopic",
              "allow_multi_issue": False, "issues": issues}
    write_json(issues_path, result)
    print(f"[group] {len(issues)} issues, {sum(len(v) for v in members.values())} memberships; "
          f"model-named {sum(i['name_source'] == 'model' for i in issues)}")
    con.close()
    return result


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--effort", default="none")
    ap.add_argument("--max-output-tokens", type=int, default=6000)
    ap.add_argument("--budget", type=float, default=0.2)
    return ap


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
