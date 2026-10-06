"""100-review cost/runtime calculator - OFFLINE REPLAY by default (no API key, no model calls).

Recomputes every cost from saved per-call usage (cost/pilot_calls.jsonl) x editable rates (cost/rates.csv),
reports the measured cold/warm pilot by stage, and projects the full corpus under base/conservative
scenarios with editable controls (cost/calculator_config.json or CLI flags).

  python3 cost/calculator.py                       # offline replay -> cost/report.md
  python3 cost/calculator.py --rate-multiplier 2   # e.g. check: API spend doubles, time/local cost unchanged
  python3 cost/calculator.py --budget 10 --workers 8 --tier batch

Paid execution is a different, explicit command: python3 cost/pilot.py --execute
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

COST = Path(__file__).resolve().parent
ROLES = ["enrich", "verify", "group", "memo"]


def load_rates(path, multiplier=1.0):
    rates, sources = {}, {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r["provider"], r["model"], r["tier"])
            rates.setdefault(key, {})[r["item"]] = float(r["price_usd"]) / float(r["per_units"]) * multiplier
            sources[key] = (r["source_url"], r["checked_on"], r["currency"], r["unit"])
    return rates, sources


def call_cost(rates, c, tier=None):
    """Mutually exclusive items: uncached input, cached input, output (reasoning already inside output)."""
    r = rates.get((c["provider"], c["model"], tier or c["tier"]))
    if r is None:
        return None
    cached = c.get("cached_input_tokens", 0) or 0
    uncached = (c.get("input_tokens", 0) or 0) - cached
    return (uncached * r.get("input", 0) + cached * r.get("cached_input", r.get("input", 0))
            + (c.get("output_tokens", 0) or 0) * r.get("output", 0))


def fmt_usd(x):
    return "unknown" if x is None else f"${x:,.4f}" if x < 1 else f"${x:,.2f}"


def fmt_s(s):
    if s is None:
        return "n/a"
    return f"{s:,.1f} s" if s < 120 else f"{s / 60:,.1f} min" if s < 7200 else f"{s / 3600:,.1f} h"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(COST / "calculator_config.json"))
    ap.add_argument("--calls", default=str(COST / "pilot_calls.jsonl"))
    ap.add_argument("--records", default=str(COST / "pilot_records.jsonl"))
    ap.add_argument("--meta", default=str(COST / "pilot_meta.json"))
    ap.add_argument("--rates", default=str(COST / "rates.csv"))
    ap.add_argument("--rate-multiplier", type=float, default=1.0)
    ap.add_argument("--budget", type=float)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--tier", choices=["standard", "batch"])
    ap.add_argument("--fallback-fraction", type=float)
    ap.add_argument("--max-output-tokens", type=int)
    ap.add_argument("--out", default=str(COST / "report.md"))
    a = ap.parse_args()

    cfg = json.loads(Path(a.config).read_text())
    for k in ("budget", "workers", "tier", "fallback_fraction", "max_output_tokens"):
        v = getattr(a, k)
        if v is not None:
            cfg["controls"][k if k != "budget" else "budget_usd"] = v
    ctl, proj = cfg["controls"], cfg["projection"]
    rates, sources = load_rates(a.rates, a.rate_multiplier)
    calls = [json.loads(l) for l in open(a.calls, encoding="utf-8") if l.strip()]
    records = [json.loads(l) for l in open(a.records, encoding="utf-8") if l.strip()]
    meta = json.loads(Path(a.meta).read_text())

    # ---------------- measured pilot
    by = defaultdict(lambda: defaultdict(float))
    stage_info = {}
    for c in calls:
        key = (c["pilot_phase"], c["role"])
        s = by[key]
        s["attempts"] += 1
        s["requests"] += c.get("attempt", 1) == 1 and c.get("retry_kind", "initial") in ("initial", None)
        s["failed"] += c["outcome"] == "failed"
        s["retries"] += c.get("attempt", 1) > 1 or c.get("retry_kind") == "invalid_output_retry"
        for f in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"):
            s[f] += c.get(f, 0) or 0
        s["latency_s"] += c.get("latency_s", 0) or 0
        s["local_compute_s"] += c.get("local_compute_s") or 0
        cost = call_cost(rates, c)
        if cost is None:
            s["unknown_cost_calls"] += 1
        else:
            s["api_cost_usd"] += cost
        s["reviews_sent"] += len(c.get("review_ids", []))
        stage_info[c["role"]] = (c["provider"], c["model"], c.get("effort"), c["tier"], c.get("label_config"),
                                 c.get("batch_size") or "-")
    completed = sum(r["status"] == "completed" for r in records)
    quarantined = sum(r["status"] == "quarantined" for r in records)
    cache_hits = sum(1 for r in records if r.get("cache_source_id"))
    unique_texts = completed - cache_hits
    cold_cost = sum(by[("cold", r)]["api_cost_usd"] for r in ROLES)
    warm_cost = sum(by[("warm", r)]["api_cost_usd"] for r in ROLES)
    cold = meta["timing"]["cold"]
    warm = meta["timing"]["warm"]
    enr = by[("cold", "enrich")]

    L = []
    L.append("# 100-review cost & runtime calculator — measured pilot and full-run projection\n")
    L.append(f"Offline replay of saved evidence; rates from `{Path(a.rates).name}`"
             + (f" × **{a.rate_multiplier}** (what-if)" if a.rate_multiplier != 1 else "") + ". No model calls were made to produce this report.\n")
    L.append("## Measured: 100-review pilot (`data/cost_100.csv`)\n")
    L.append(f"* Input SHA-256 `{meta['input_sha256']}` · IDs: {len(records)} · completed **{completed}** · "
             f"quarantined/failed **{quarantined}** · unique texts sent {unique_texts} · result-cache hits {cache_hits}")
    L.append(f"* Workers 1 · enrichment batch size {meta['batch_size']} · declared verification sample {meta['verify_sample_declared']} reviews")
    L.append(f"* **Cold** end-to-end wall clock: **{fmt_s(cold['wall_clock_s'])}** · API spend **{fmt_usd(cold_cost)}** · calls {cold['new_calls']}")
    L.append(f"* **Warm** (saved results, unchanged settings): **{fmt_s(warm['wall_clock_s'])}** · new enrichment calls "
             f"**{warm['new_enrich_calls']}** · all new calls {warm['new_calls']} · incremental API spend {fmt_usd(warm_cost)}\n")
    L.append("| phase | stage | provider / model / effort / tier | requests | attempts | failed | retries | input tok | cached tok | output tok | reasoning tok | API cost | local compute |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for phase in ("cold", "warm"):
        for role in ROLES:
            s = by.get((phase, role))
            if not s:
                L.append(f"| {phase} | {role} | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0 | — |")
                continue
            p, m, e, t, lc, bs = stage_info[role]
            unk = f" (+{int(s['unknown_cost_calls'])} unknown)" if s["unknown_cost_calls"] else ""
            L.append(f"| {phase} | {role} | {p} / `{m}` / {e} / {t} | {int(s['requests'])} | {int(s['attempts'])} | {int(s['failed'])} | "
                     f"{int(s['retries'])} | {int(s['input_tokens']):,} | {int(s['cached_input_tokens']):,} | {int(s['output_tokens']):,} | "
                     f"{int(s['reasoning_tokens']):,} | {fmt_usd(s['api_cost_usd'])}{unk} | {fmt_s(s['local_compute_s']) if s['local_compute_s'] else '—'} |")
    L.append("")
    L.append("Prompt/schema versions (label_config): " + "; ".join(f"{r}: `{stage_info[r][4]}`" for r in ROLES if r in stage_info) + "\n")
    enrich_s = cold["stage_seconds"].get("enrich", 0)
    L.append(f"* Cost per 1,000 input rows (cold, all stages): **{fmt_usd(cold_cost / len(records) * 1000)}** · "
             f"per completed record: {fmt_usd(cold_cost / completed if completed else None)}")
    L.append(f"* Enrichment throughput (1 worker): {completed / enrich_s if enrich_s else 0:.2f} records/s "
             f"({enrich_s:.1f} s for the stage) · stage seconds: " + ", ".join(f"{k} {v}s" for k, v in cold["stage_seconds"].items()))
    L.append("* Summed call latency ≠ wall clock when calls overlap; wall clock above is measured with a clock around the whole command.\n")

    # ---------------- projection
    n_rows, n_nonempty, n_empty, n_distinct = proj["rows"], proj["nonempty"], proj["empty"], proj["distinct_texts"]
    texts_sent = max(1, unique_texts)
    tok_in = enr["input_tokens"] / texts_sent           # includes retries + fixed prompt share at the pilot batch size
    tok_cached = enr["cached_input_tokens"] / texts_sent
    tok_out = enr["output_tokens"] / texts_sent
    enrich_rate_key = (stage_info["enrich"][0], stage_info["enrich"][1])
    tier = ctl["tier"]
    per_text = lambda mi, mo: call_cost(rates, {"provider": enrich_rate_key[0], "model": enrich_rate_key[1], "tier": tier,  # noqa: E731
                                                "input_tokens": tok_in * mi, "cached_input_tokens": tok_cached * mi,
                                                "output_tokens": min(tok_out * mo, ctl["max_output_tokens"] / meta["batch_size"])})
    fb = cfg["fallback"]
    fb_per_text = call_cost(rates, {"provider": fb["provider"], "model": fb["model"], "tier": fb["tier"],
                                    "input_tokens": tok_in, "cached_input_tokens": 0, "output_tokens": tok_out})
    v = by[("cold", "verify")]
    v_sent = max(1, v["reviews_sent"])
    verify_cost_per = v["api_cost_usd"] / v_sent
    verify_time_per = (v["local_compute_s"] or v["latency_s"]) / v_sent
    fixed_cost = by[("cold", "group")]["api_cost_usd"] + by[("cold", "memo")]["api_cost_usd"]
    fixed_time = sum(cold["stage_seconds"].get(k, 0) for k in ("group", "memo"))
    sec_per_batch = (enrich_s / max(1, enr["requests"])) if enr["requests"] else 0
    workers = ctl["workers"]

    def scenario(name, texts, mi, mo, retry_extra, time_mult, fixed_mult):
        api_enrich = texts * (per_text(mi, mo) or 0) * (1 + retry_extra)
        fallback = texts * ctl["fallback_fraction"] * (fb_per_text or 0)
        verify_n = min(proj["verify_max_sample"], math.ceil(texts * proj["verify_rate"]))
        api_verify = verify_n * verify_cost_per
        api_fixed = fixed_cost * fixed_mult
        batches = math.ceil(texts / meta["batch_size"]) * (1 + retry_extra)
        t_enrich = batches * sec_per_batch * time_mult / workers
        t_verify = verify_n * verify_time_per * time_mult  # local verifier runs concurrently with nothing else
        total = api_enrich + fallback + api_verify + api_fixed
        return {"name": name, "texts": texts, "api_enrich": api_enrich, "api_fallback": fallback,
                "verify_n": verify_n, "api_verify": api_verify, "api_fixed": api_fixed, "api_total": total,
                "t_enrich": t_enrich, "t_verify": t_verify, "t_fixed": fixed_time * fixed_mult + proj["ingest_seconds"],
                "t_total": t_enrich + t_verify + fixed_time * fixed_mult + proj["ingest_seconds"],
                "over_budget": total > ctl["budget_usd"]}

    c = cfg["conservative"]
    scen = [scenario("base, exact-text reuse", n_distinct, 1, 1, 0, 1, 1),
            scenario("conservative, exact-text reuse", n_distinct, 1 + c["token_margin"], 1 + c["token_margin"], c["retry_rate"],
                     c["time_multiplier"], c["fixed_multiplier"]),
            scenario("base, NO reuse", n_nonempty, 1, 1, 0, 1, 1),
            scenario("conservative, NO reuse", n_nonempty, 1 + c["token_margin"], 1 + c["token_margin"], c["retry_rate"],
                     c["time_multiplier"], c["fixed_multiplier"])]
    L.append("## Projection: full corpus\n")
    L.append(f"* Rows **{n_rows:,}** = {n_nonempty:,} nonempty classifications + {n_empty} empty-text quarantines (no model call). "
             f"Distinct nonempty texts with valid exact-text reuse: **{n_distinct:,}**.")
    L.append(f"* Measured per sent text (enrich, incl. its retries and the fixed prompt share at batch size {meta['batch_size']}): "
             f"{tok_in:.1f} input tok ({tok_cached:.1f} cached), {tok_out:.1f} output tok.")
    L.append(f"* Controls: budget **${ctl['budget_usd']:.2f}** · workers {workers} · tier `{tier}`"
             f"{' (hypothetical: not the measured tier)' if tier != stage_info['enrich'][3] else ''} · output-token cap "
             f"{ctl['max_output_tokens']}/request · fallback fraction {ctl['fallback_fraction']:.1%} to `{fb['model']}` · "
             f"verification {proj['verify_rate']:.1%} of texts, max {proj['verify_max_sample']:,} (local)")
    L.append(f"* Conservative: +{c['token_margin']:.0%} tokens, +{c['retry_rate']:.0%} retried batches, ×{c['time_multiplier']} time, "
             f"×{c['fixed_multiplier']} group/memo (larger packs). Group + memo are fixed overhead, counted once.\n")
    L.append("| scenario | texts | enrich API | fallback API | verify (n, API) | group+memo API | **API total** | enrich time | verify time (local) | **total time** | budget |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in scen:
        L.append(f"| {s['name']} | {s['texts']:,} | {fmt_usd(s['api_enrich'])} | {fmt_usd(s['api_fallback'])} | {s['verify_n']:,}, "
                 f"{fmt_usd(s['api_verify'])} | {fmt_usd(s['api_fixed'])} | **{fmt_usd(s['api_total'])}** | {fmt_s(s['t_enrich'])} | "
                 f"{fmt_s(s['t_verify'])} | **{fmt_s(s['t_total'])}** | {'⚠️ EXCEEDS' if s['over_budget'] else 'within'} |")
    L.append("")
    L.append("**Separate from API spend:** local verifier compute (Ollama on the author's Apple M4, 24 GB) has no API charge; "
             "electricity/hardware cost is **unknown, not zero**, and is reported as time only. Delayed provider billing means "
             "the local ledger is not a guarantee; the OpenAI account also has a hard usage limit.\n")
    L.append("## Rates used (editable `cost/rates.csv`)\n")
    L.append("| provider | model | tier | item | USD per 1M units | source | checked |")
    L.append("|---|---|---|---|---|---|---|")
    for (p, m, t), items in sorted(rates.items()):
        for item, per in items.items():
            src, checked, cur, unit = sources[(p, m, t)]
            L.append(f"| {p} | {m} | {t} | {item} | {per * 1e6:.4f} | {src} | {checked} |")
    L.append("\nFormula: `item_cost = billed_units × price_per_unit`; uncached input = input − cached input; reasoning tokens are already inside output and are not added again.")
    Path(a.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
