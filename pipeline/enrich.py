"""Stage 2 - Classify (role: enrich).

Code decides WHAT to send (pending distinct texts, <=50 per request), validates every returned ID and
field, retries invalid output once, reuses exact-text results under the same label_config, and commits
results + statuses atomically after each batch. The model only reads language and picks labels.

Stop conditions: no pending work, spend cap (reserve-before-dispatch), --max-batches, --time-limit,
Ctrl+C (finishes in-flight batches, saves, exits). Re-running resumes: completed IDs are never resent.

Usage:
  python -m pipeline.enrich --db work/full/pipeline.sqlite --run-dir outputs/runs/full \
      --provider openai --model gpt-6-luna --effort none --budget 15 --workers 4
"""

import argparse
import json
import signal
import sqlite3
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .common import append_jsonl, now_iso, write_json
from .llm import BudgetExceeded, SpendLedger, call_with_backoff, load_env, load_rates, make_provider, usage_cost
from .schema import enrich_json_schema, label_config, prompt_text, validate_item

PROMPT = "enrich_v1"

RESULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
  text_sha256 TEXT NOT NULL, label_config TEXT NOT NULL, source_review_id TEXT NOT NULL,
  topic TEXT, subtopic TEXT, intent TEXT, severity INTEGER, sentiment REAL, evidence_quote TEXT,
  entities TEXT, needs_review INTEGER, request_id TEXT, created_at TEXT,
  PRIMARY KEY (text_sha256, label_config)
);
"""
STATUS_COLUMNS = {"label_config": "TEXT", "cache_source_id": "TEXT", "request_id": "TEXT"}


def prepare_db(con):
    con.executescript(RESULT_SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(status)")}
    for col, typ in STATUS_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE status ADD COLUMN {col} {typ}")
    con.commit()


class RateLimiter:
    """Shared minimum interval between request starts (requests-per-minute cap) across workers."""

    def __init__(self, rpm):
        self.interval = 60.0 / rpm if rpm else 0
        self.next = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next - now)
            self.next = max(now, self.next) + self.interval
        if delay:
            time.sleep(delay)


class Enricher:
    def __init__(self, args):
        self.a = args
        load_env()
        self.provider = make_provider(args.provider, args.model, args.effort, args.max_output_tokens)
        self.rates = load_rates()
        self.cfg = label_config(args.model, args.effort, PROMPT)
        self.system = prompt_text(PROMPT)
        self.schema = enrich_json_schema()
        self.run_dir = Path(args.run_dir)
        self.calls_path = self.run_dir / "calls.jsonl"
        self.log_path = self.run_dir / "run_log.jsonl"
        self.log_lock = threading.Lock()
        prior = self._prior_spend()
        self.ledger = SpendLedger(args.budget, prior)
        self.limiter = RateLimiter(args.rpm)
        self.stop_reason = None
        self.run_id = args.run_id or time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]

    # ---------- logging
    def _prior_spend(self):
        """Budget is cumulative across resumes of the same run directory."""
        total = 0.0
        if self.calls_path.exists():
            for line in self.calls_path.open(encoding="utf-8"):
                c = json.loads(line)
                if c.get("role") == "enrich" and c.get("cost_usd") is not None:
                    total += c["cost_usd"]
        return total

    def log(self, event, **kw):
        with self.log_lock:
            append_jsonl(self.log_path, {"ts": now_iso(), "run_id": self.run_id, "stage": "enrich", "event": event, **kw})

    def log_call(self, res, attempt, ids, batch_id, retry_kind, phase, parse_error=None):
        cost = usage_cost(self.rates, self.provider.name, self.a.model, self.provider.tier, res.usage) if res.usage else 0.0
        if not res.usage and not res.ok:
            cost = None if res.transient and "network" in res.error else 0.0  # timeouts: charge unknown
        rec = {"request_id": res.request_id, "role": "enrich", "review_ids": ids, "model": self.a.model,
               "provider": self.provider.name, "effort": self.a.effort, "tier": self.provider.tier, "phase": phase,
               "outcome": "succeeded" if res.ok and not parse_error else "failed", "label_config": self.cfg,
               "input_tokens": int(res.usage.get("input_tokens", 0) or 0),
               "cached_input_tokens": int(res.usage.get("cached_input_tokens", 0) or 0),
               "output_tokens": int(res.usage.get("output_tokens", 0) or 0),
               "reasoning_tokens": int(res.usage.get("reasoning_tokens", 0) or 0),
               "local_compute_s": res.usage.get("local_compute_s"),
               "cost_usd": cost, "latency_s": round(res.latency_s, 3), "attempt": attempt, "retry_kind": retry_kind,
               "batch_id": batch_id, "batch_size": len(ids), "error": res.error or parse_error or None,
               "run_id": self.run_id, "prompt": PROMPT, "ts": now_iso()}
        with self.log_lock:
            append_jsonl(self.calls_path, rec)
        return cost

    # ---------- one request (runs in a worker thread)
    def _request(self, items, batch_id, retry_kind, phase):
        """items: list of (review_id, text). Returns (parsed_list_or_None, total_cost, error)."""
        ids = [rid for rid, _ in items]
        payload = [{"id": f"r{i + 1}", "text": t} for i, (_, t) in enumerate(items)]
        user = "Label these reviews:\n" + json.dumps(payload, ensure_ascii=False)
        est_in = (len(self.system) + len(user)) // 3 + 50
        worst = usage_cost(self.rates, self.provider.name, self.a.model, self.provider.tier,
                           {"input_tokens": est_in, "output_tokens": self.a.max_output_tokens}) or 0.0
        reservation = self.ledger.reserve(worst * (self.a.max_transient_retries + 1))
        spent = 0.0

        kind = lambda attempt: retry_kind if attempt == 1 else retry_kind + "+transient"  # noqa: E731

        def on_attempt(res, attempt):
            nonlocal spent
            if res.ok:
                return  # logged below, once its output has been parsed
            c = self.log_call(res, attempt, ids, batch_id, kind(attempt), phase)
            spent += worst if c is None else c

        self.limiter.wait()
        res, attempt = call_with_backoff(self.provider, self.system, user, self.schema, "enrich_results",
                                         self.a.max_transient_retries, on_attempt=on_attempt)
        if not res.ok:
            self.ledger.settle(reservation, spent)
            return None, ("transient_exhausted: " if res.transient else "call_failed: ") + res.error, res.transient
        parse_error = None
        try:
            parsed = json.loads(res.text)["results"]
            if not isinstance(parsed, list):
                raise ValueError("results is not a list")
        except (ValueError, KeyError, TypeError) as e:
            parse_error = f"malformed_output: {e}"
        spent += self.log_call(res, attempt, ids, batch_id, kind(attempt), phase, parse_error) or 0.0
        self.ledger.settle(reservation, spent)
        if parse_error:
            return None, parse_error, False
        return (parsed, res.request_id), None, False

    def _validate(self, items, parsed):
        """Exact ID accounting: returns ({rid: fields}, {rid: reason})."""
        by_local = {f"r{i + 1}": (rid, text) for i, (rid, text) in enumerate(items)}
        good, bad, seen = {}, {}, set()
        for obj in parsed:
            lid = obj.get("id") if isinstance(obj, dict) else None
            if lid not in by_local or lid in seen:
                continue  # unknown or duplicate IDs are ignored; the real ID ends up missing below
            seen.add(lid)
            rid, text = by_local[lid]
            fields, err = validate_item(obj, text)
            if err:
                bad[rid] = err
            else:
                good[rid] = fields
        for lid, (rid, _) in by_local.items():
            if lid not in seen:
                bad[rid] = "missing_id_in_output"
        return good, bad

    def process_batch(self, items, batch_id, phase):
        """Runs in a worker. One invalid-output retry for the failing subset, then give up on those IDs."""
        out = {"batch_id": batch_id, "good": {}, "bad": {}, "transient": {}, "request_ids": {}}
        r, err, transient = self._request(items, batch_id, "initial", phase)
        if r:
            parsed, req_id = r
            good, bad = self._validate(items, parsed)
            for rid in good:
                out["request_ids"][rid] = req_id
            out["good"].update(good)
            retry_items = [(rid, t) for rid, t in items if rid in bad]
            first_errors = bad
        elif transient:
            out["transient"] = {rid: err for rid, _ in items}
            return out
        else:
            retry_items, first_errors = items, {rid: err for rid, _ in items}
        if retry_items:
            try:
                r2, err2, transient2 = self._request(retry_items, batch_id, "invalid_output_retry", phase)
            except BudgetExceeded as e:  # keep the good results; leave the retry subset pending
                out["transient"].update({rid: f"budget: {e}" for rid, _ in retry_items})
                return out
            if r2:
                parsed, req_id = r2
                good, bad = self._validate(retry_items, parsed)
                for rid in good:
                    out["request_ids"][rid] = req_id
                out["good"].update(good)
                out["bad"].update({rid: f"{first_errors[rid]}; retry: {bad[rid]}" for rid in bad})
            elif transient2:
                out["transient"].update({rid: err2 for rid, _ in retry_items})
            else:
                out["bad"].update({rid: f"{first_errors[rid]}; retry: {err2}" for rid, _ in retry_items})
        return out

    # ---------- state (main thread only)
    def apply_cache(self, con):
        """Exact-text reuse: pending rows whose text already has a validated result under this label_config."""
        n = con.execute("""
            UPDATE status SET status='completed', label_config=?, updated_at=?,
              cache_source_id=(SELECT r.source_review_id FROM results r JOIN reviews v ON v.text_sha256=r.text_sha256
                               WHERE v.review_id=status.review_id AND r.label_config=?),
              request_id=NULL
            WHERE status='pending' AND review_id IN (
              SELECT v.review_id FROM reviews v JOIN results r ON r.text_sha256=v.text_sha256 AND r.label_config=?)
        """, (self.cfg, now_iso(), self.cfg, self.cfg)).rowcount
        # the original that was actually sent is never its own cache alias
        con.execute("UPDATE status SET cache_source_id=NULL WHERE cache_source_id=review_id")
        con.commit()
        return n

    def pending_texts(self, con):
        """One representative (the canonical first occurrence) per pending distinct text, in source order."""
        return con.execute("""
            SELECT v.review_id, v.review_text, v.text_sha256 FROM reviews v JOIN status s ON s.review_id=v.review_id
            WHERE s.status='pending' AND v.is_empty=0 AND v.canonical_id=v.review_id ORDER BY v.row_num
        """).fetchall()

    def commit_batch(self, con, items, out):
        ts = now_iso()
        sha = {rid: tsha for rid, _, tsha in items}
        with con:  # one transaction per batch: results + all statuses, or nothing
            for rid, f in out["good"].items():
                con.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sha[rid], self.cfg, rid, f["topic"], f["subtopic"], f["intent"], f["severity"],
                             f["sentiment"], f["evidence_quote"], json.dumps(f["entities"]), int(f["needs_review"]),
                             out["request_ids"][rid], ts))
                con.execute("UPDATE status SET status='completed', label_config=?, request_id=?, cache_source_id=NULL, "
                            "attempts=attempts+1, reason=NULL, updated_at=? WHERE review_id=?",
                            (self.cfg, out["request_ids"][rid], ts, rid))
                # all other rows with identical text reuse this result, pointing directly at the original
                con.execute("UPDATE status SET status='completed', label_config=?, cache_source_id=?, updated_at=? "
                            "WHERE status='pending' AND review_id IN (SELECT review_id FROM reviews WHERE text_sha256=? "
                            "AND review_id<>?)", (self.cfg, rid, ts, sha[rid], rid))
            for rid, reason in out["bad"].items():
                con.execute("UPDATE status SET status='quarantined', reason=?, attempts=attempts+2, label_config=?, "
                            "updated_at=? WHERE review_id IN (SELECT review_id FROM reviews WHERE text_sha256=?) "
                            "AND status='pending'", (reason[:300], self.cfg, ts, sha[rid]))
            for rid, reason in out["transient"].items():
                con.execute("UPDATE status SET attempts=attempts+1, reason=?, updated_at=? WHERE review_id=?",
                            (reason[:300], ts, rid))

    def counts(self, con):
        return dict(con.execute("SELECT status, COUNT(*) FROM status GROUP BY status").fetchall())

    def completed_ids(self, con):
        return [r[0] for r in con.execute("SELECT review_id FROM status WHERE status='completed' ORDER BY review_id")]

    # ---------- main loop
    def run(self):
        a = self.a
        self.run_dir.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(a.db)
        prepare_db(con)
        already = con.execute("SELECT COUNT(*) FROM status WHERE status='completed' AND label_config=?",
                              (self.cfg,)).fetchone()[0]
        phase = a.phase if a.phase != "auto" else ("resume" if already else "initial")
        t0 = time.time()
        before = self.counts(con)
        cache_hits_start = self.apply_cache(con)
        todo = self.pending_texts(con)
        self.log("start", phase=phase, label_config=self.cfg, provider=self.provider.name, model=a.model,
                 effort=a.effort, batch_size=a.batch_size, workers=a.workers, budget_usd=a.budget,
                 prior_spend_usd=round(self.ledger.spent, 6), counts_before=before,
                 cache_hits_at_start=cache_hits_start, pending_distinct_texts=len(todo))
        print(f"[enrich] phase={phase} pending distinct texts={len(todo)} cache hits applied={cache_hits_start} "
              f"label_config={self.cfg}")

        batches = []
        cur, chars = [], 0
        for row in todo:
            if cur and (len(cur) >= a.batch_size or chars + len(row[1]) > a.max_batch_chars):
                batches.append(cur)
                cur, chars = [], 0
            cur.append(row)
            chars += len(row[1])
        if cur:
            batches.append(cur)
        if a.max_batches is not None:
            batches = batches[:a.max_batches]

        stop = threading.Event()

        def on_sigint(sig, frame):
            if stop.is_set():
                raise KeyboardInterrupt
            self.stop_reason = self.stop_reason or "interrupted (SIGINT)"
            print("\n[enrich] interrupt received: finishing in-flight batches, saving, then exiting...")
            stop.set()
        old = signal.signal(signal.SIGINT, on_sigint)

        done_batches = consecutive_transient = 0
        inflight = {}
        it = iter(enumerate(batches))
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            while True:
                while not stop.is_set() and len(inflight) < a.workers:
                    if a.time_limit and time.time() - t0 > a.time_limit:
                        self.stop_reason = "time_limit"
                        stop.set()
                        break
                    nxt = next(it, None)
                    if nxt is None:
                        break
                    i, b = nxt
                    items = [(rid, text) for rid, text, _ in b]
                    bid = f"{self.run_id}-b{i:06d}"
                    try:
                        fut = pool.submit(self.process_batch, items, bid, phase)
                    except BudgetExceeded as e:
                        self.stop_reason = f"budget: {e}"
                        stop.set()
                        break
                    inflight[fut] = b
                if not inflight:
                    break
                finished, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in finished:
                    b = inflight.pop(fut)
                    try:
                        out = fut.result()
                    except BudgetExceeded as e:
                        self.stop_reason = f"budget: {e}"
                        stop.set()
                        continue
                    self.commit_batch(con, b, out)
                    done_batches += 1
                    consecutive_transient = consecutive_transient + 1 if out["transient"] and not out["good"] else 0
                    if consecutive_transient >= a.max_consecutive_failures:
                        self.stop_reason = f"{consecutive_transient} consecutive failed batches"
                        stop.set()
                    if done_batches % a.progress_every == 0 or len(out["bad"]) or len(out["transient"]):
                        c = self.counts(con)
                        print(f"[enrich] batches {done_batches}/{len(batches)} completed={c.get('completed', 0)} "
                              f"quarantined={c.get('quarantined', 0)} pending={c.get('pending', 0)} "
                              f"spent=${self.ledger.spent:.4f} bad={len(out['bad'])} transient={len(out['transient'])}")
        signal.signal(signal.SIGINT, old)
        self.stop_reason = self.stop_reason or ("max_batches" if a.max_batches is not None and
                                                done_batches < len(todo) / max(1, a.batch_size) else "no_pending_work")
        after = self.counts(con)
        summary = {"run_id": self.run_id, "finished_at": now_iso(), "phase": phase, "label_config": self.cfg,
                   "provider": self.provider.name, "model": a.model, "effort": a.effort, "tier": self.provider.tier,
                   "batch_size": a.batch_size, "workers": a.workers, "rpm": a.rpm,
                   "max_output_tokens": a.max_output_tokens, "batches_done": done_batches,
                   "batches_planned": len(batches), "wall_clock_s": round(time.time() - t0, 2),
                   "counts_before": before, "counts_after": after, "cache_hits_at_start": cache_hits_start,
                   "ledger": self.ledger.snapshot(), "stop_reason": self.stop_reason}
        write_json(self.run_dir / f"enrich_summary_{self.run_id}.json", summary)
        if a.snapshot:
            write_json(a.snapshot, {"run_id": self.run_id, "taken_at": now_iso(), "label_config": self.cfg,
                                    "counts": after, "completed_ids": self.completed_ids(con)})
        self.log("stop", **{k: summary[k] for k in ("stop_reason", "batches_done", "wall_clock_s", "counts_after", "ledger")})
        print(f"[enrich] stop: {self.stop_reason}; {after}; spent ${self.ledger.spent:.4f}; "
              f"{summary['wall_clock_s']}s")
        con.close()
        return summary


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--run-id")
    ap.add_argument("--provider", default="openai", choices=["openai", "ollama", "fake"])
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--effort", default="none")
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--max-batch-chars", type=int, default=20000)
    ap.add_argument("--max-output-tokens", type=int, default=4000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rpm", type=float, default=300, help="global requests-per-minute cap across workers")
    ap.add_argument("--budget", type=float, default=1.0, help="USD spending cap for this run directory (cumulative)")
    ap.add_argument("--max-transient-retries", type=int, default=4)
    ap.add_argument("--max-consecutive-failures", type=int, default=5)
    ap.add_argument("--max-batches", type=int)
    ap.add_argument("--time-limit", type=float, help="seconds")
    ap.add_argument("--phase", default="auto", choices=["auto", "initial", "resume"])
    ap.add_argument("--snapshot", help="write completed_ids checkpoint JSON here at exit")
    ap.add_argument("--progress-every", type=int, default=20)
    return ap


def main(argv=None):
    return Enricher(build_parser().parse_args(argv)).run()


if __name__ == "__main__":
    main()
