"""Model providers, editable rates, and a shared spend ledger.

Providers return a uniform CallResult with raw usage. No provider is contacted at import time.
Keys come from the environment (.env loaded by load_env); they are never logged.

  openai   - OpenAI Responses API, structured JSON-schema output, reasoning.effort configurable
  ollama   - local Ollama server (zero API charge; local compute reported separately)
  fake     - deterministic offline provider for tests (synthetic; never used for business results)
"""

import csv
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

from .common import ROOT

RATES_CSV = ROOT / "cost" / "rates.csv"


def load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


# ---------------------------------------------------------------- rates

def load_rates(path=RATES_CSV):
    """{(provider, model, tier): {item: usd_per_unit}} - prices per million tokens converted to per token."""
    rates = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            per_unit = float(r["price_usd"]) / float(r["per_units"])
            rates.setdefault((r["provider"], r["model"], r["tier"]), {})[r["item"]] = per_unit
    return rates


def usage_cost(rates, provider, model, tier, usage):
    """Mutually exclusive items: uncached input, cached input, output (reasoning is already inside output)."""
    r = rates.get((provider, model, tier))
    if r is None:
        return None  # unknown rate -> unknown cost, never silently zero
    cached = usage.get("cached_input_tokens", 0) or 0
    uncached = (usage.get("input_tokens", 0) or 0) - cached
    return (uncached * r.get("input", 0) + cached * r.get("cached_input", r.get("input", 0))
            + (usage.get("output_tokens", 0) or 0) * r.get("output", 0))


class BudgetExceeded(Exception):
    pass


class SpendLedger:
    """One ledger shared by all workers. Reserve worst-case cost before dispatch; settle with actual usage.

    Admission rule: refuse when spent + reserved + next_reservation > cap.
    """

    def __init__(self, cap_usd, spent_usd=0.0):
        self.cap = cap_usd
        self.spent = spent_usd
        self.reserved = 0.0
        self.lock = threading.Lock()

    def reserve(self, amount):
        with self.lock:
            if self.spent + self.reserved + amount > self.cap:
                raise BudgetExceeded(f"spent {self.spent:.4f} + reserved {self.reserved:.4f} + next {amount:.4f} "
                                     f"> cap {self.cap:.4f}")
            self.reserved += amount
            return amount

    def settle(self, reservation, actual):
        with self.lock:
            self.reserved -= reservation
            # unknown actual cost (e.g. timeout) is charged at the reserved worst case
            self.spent += reservation if actual is None else actual

    def snapshot(self):
        with self.lock:
            return {"cap_usd": self.cap, "spent_usd": round(self.spent, 6), "reserved_usd": round(self.reserved, 6)}


# ---------------------------------------------------------------- providers

@dataclass
class CallResult:
    ok: bool
    request_id: str
    text: str = ""
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    error: str = ""
    transient: bool = False      # retry with backoff (rate limit, 5xx, timeout)
    raw_status: str = ""


class OpenAIProvider:
    name = "openai"
    URL = "https://api.openai.com/v1/responses"

    def __init__(self, model, effort="none", max_output_tokens=4000, timeout=120, tier="standard"):
        self.model, self.effort, self.max_output_tokens, self.timeout, self.tier = model, effort, max_output_tokens, timeout, tier
        self.key = os.environ.get("OPENAI_API_KEY", "")
        if not self.key:
            raise RuntimeError("OPENAI_API_KEY is not set (copy .env.example to .env and fill it in)")

    def call(self, system, user, schema, schema_name):
        body = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": self.max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
            "store": False,
        }
        if self.effort:
            body["reasoning"] = {"effort": self.effort}
        req = urllib.request.Request(self.URL, json.dumps(body).encode(), {
            "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        t0 = time.time()
        local_id = "local-" + uuid.uuid4().hex[:12]
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
                rid = resp.headers.get("x-request-id") or data.get("id") or local_id
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            return CallResult(False, e.headers.get("x-request-id") or local_id, latency_s=time.time() - t0,
                              error=f"http_{e.code}: {msg}", transient=e.code in (408, 409, 429, 500, 502, 503, 504))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            return CallResult(False, local_id, latency_s=time.time() - t0, error=f"network: {e}", transient=True)
        u = data.get("usage") or {}
        usage = {"input_tokens": u.get("input_tokens", 0),
                 "cached_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens", 0),
                 "output_tokens": u.get("output_tokens", 0),
                 "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0)}
        text = "".join(c.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
                       for c in item.get("content", []) if c.get("type") == "output_text")
        status = data.get("status", "")
        if status != "completed" or not text:
            reason = (data.get("incomplete_details") or {}).get("reason", status)
            return CallResult(False, rid, text, usage, time.time() - t0, f"incomplete: {reason}", raw_status=status)
        return CallResult(True, rid, text, usage, time.time() - t0, raw_status=status)


class OllamaProvider:
    name = "ollama"

    def __init__(self, model, effort="none", max_output_tokens=4000, timeout=900, tier="local"):
        self.model, self.effort, self.max_output_tokens, self.timeout, self.tier = model, effort, max_output_tokens, timeout, tier
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def call(self, system, user, schema, schema_name):
        body = {"model": self.model, "stream": False, "think": self.effort not in ("none", None, ""),
                "format": schema, "options": {"temperature": 0, "num_predict": self.max_output_tokens, "num_ctx": 16384},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        req = urllib.request.Request(f"{self.host}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        t0 = time.time()
        rid = "ollama-" + uuid.uuid4().hex[:12]
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            return CallResult(False, rid, latency_s=time.time() - t0, error=f"http_{e.code}", transient=e.code >= 500)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            return CallResult(False, rid, latency_s=time.time() - t0, error=f"network: {e}", transient=True)
        usage = {"input_tokens": data.get("prompt_eval_count", 0), "cached_input_tokens": 0,
                 "output_tokens": data.get("eval_count", 0), "reasoning_tokens": 0,
                 "local_compute_s": round(data.get("total_duration", 0) / 1e9, 3)}
        text = (data.get("message") or {}).get("content", "")
        if data.get("done_reason") == "length":
            return CallResult(False, rid, text, usage, time.time() - t0, "incomplete: max_output_tokens")
        return CallResult(bool(text), rid, text, usage, time.time() - t0, "" if text else "empty_response")


class FakeProvider:
    """Deterministic test double. Labels by keyword; can inject failures. Output is SYNTHETIC."""
    name = "fake"

    def __init__(self, model="fake-keyword-v1", effort="none", max_output_tokens=4000, tier="test",
                 fail_plan=None, latency=0.0):
        self.model, self.effort, self.max_output_tokens, self.tier = model, effort, max_output_tokens, tier
        self.fail_plan = list(fail_plan or [])  # e.g. ["transient", "malformed", "drop_id", "bad_quote"]
        self.latency = latency
        self.lock = threading.Lock()

    def call(self, system, user, schema, schema_name):
        with self.lock:
            mode = self.fail_plan.pop(0) if self.fail_plan else "ok"
        time.sleep(self.latency)
        rid = "fake-" + uuid.uuid4().hex[:12]
        items = json.loads(user.split("\n", 1)[1])
        usage = {"input_tokens": (len(system) + len(user)) // 4, "cached_input_tokens": 0, "output_tokens": 0}
        if mode == "transient":
            return CallResult(False, rid, usage={}, error="http_429: synthetic rate limit", transient=True)
        if mode == "malformed":
            usage["output_tokens"] = 5
            return CallResult(True, rid, '{"results": [', usage)
        out = []
        for it in items:
            t = it["text"].lower()
            topic = ("access" if "login" in t or "log in" in t else "playback" if "crash" in t
                     else "usability" if " ad" in t else "other")
            sub = {"access": "login_failure", "playback": "crash_freeze", "usability": "ads", "other": "general"}[topic]
            neg = any(w in t for w in ("bad", "worst", "crash", "can't", "hate", "ads"))
            intent, sev, sent = ("complaint", 3, -0.5) if neg else ("praise", 1, 0.6)
            if "verify" in schema_name:
                row = {"id": it["id"], "topic": topic, "intent": intent, "severity": sev, "sentiment": sent}
            else:
                row = {"id": it["id"], "label": f"{topic}.{sub}", "intent": intent, "sev": sev, "sent": sent,
                       "q": "*", "flag": False}
            out.append(row)
        if mode == "drop_id" and out:
            out.pop()
        if mode == "bad_quote" and out and "q" in out[0]:
            out[0]["q"] = "THIS TEXT IS NOT IN THE REVIEW"
            out[0]["label"] = "nonsense"
        text = json.dumps({"results": out})
        usage["output_tokens"] = len(text) // 4
        return CallResult(True, rid, text, usage)


PROVIDERS = {"openai": OpenAIProvider, "ollama": OllamaProvider, "fake": FakeProvider}


def make_provider(provider, model, effort, max_output_tokens, **kw):
    if provider == "fake" and os.environ.get("FAKE_FAIL_PLAN"):
        kw.setdefault("fail_plan", os.environ["FAKE_FAIL_PLAN"].split(","))
    return PROVIDERS[provider](model=model, effort=effort, max_output_tokens=max_output_tokens, **kw)


def call_with_backoff(provider, system, user, schema, schema_name, max_transient_retries=4, base_delay=1.0,
                      on_attempt=None):
    """Bounded exponential backoff with jitter for transient errors only. Every attempt is reported."""
    attempt = 0
    while True:
        attempt += 1
        res = provider.call(system, user, schema, schema_name)
        if on_attempt:
            on_attempt(res, attempt)
        if res.ok or not res.transient or attempt > max_transient_retries:
            return res, attempt
        time.sleep(base_delay * (2 ** (attempt - 1)) * (0.5 + random.random()))


class RoleCaller:
    """Logged, budgeted model calls for the verify / group / memo roles (enrich has its own batch logic).

    Every attempt goes to <run_dir>/calls.jsonl with the role, the review IDs actually sent, usage and cost.
    """

    def __init__(self, run_dir, role, provider, model, effort, max_output_tokens, budget_usd, config_label,
                 run_id=None, max_transient_retries=4):
        load_env()
        from .common import append_jsonl  # local import keeps llm.py import-light
        self._append = append_jsonl
        self.run_dir = __import__("pathlib").Path(run_dir)
        self.role, self.model, self.effort = role, model, effort
        self.provider = make_provider(provider, model, effort, max_output_tokens)
        self.max_output_tokens = max_output_tokens
        self.rates = load_rates()
        self.ledger = SpendLedger(budget_usd)
        self.config_label = config_label
        self.run_id = run_id or time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.max_transient_retries = max_transient_retries
        self.calls = []

    def call(self, system, user, schema, schema_name, review_ids=(), inputs_note=""):
        est_in = (len(system) + len(user)) // 3 + 50
        worst = usage_cost(self.rates, self.provider.name, self.model, self.provider.tier,
                           {"input_tokens": est_in, "output_tokens": self.max_output_tokens}) or 0.0
        reservation = self.ledger.reserve(worst * (self.max_transient_retries + 1))
        spent = 0.0
        records = []

        def on_attempt(res, attempt):
            records.append((res, attempt))

        res, _ = call_with_backoff(self.provider, system, user, schema, schema_name, self.max_transient_retries,
                                   on_attempt=on_attempt)
        parsed, parse_error = None, None
        if res.ok:
            try:
                parsed = json.loads(res.text)
            except ValueError as e:
                parse_error = f"malformed_output: {e}"
        for r, attempt in records:
            cost = usage_cost(self.rates, self.provider.name, self.model, self.provider.tier, r.usage) if r.usage else 0.0
            spent += worst if cost is None else cost
            failed = (not r.ok) or (r is res and parse_error is not None)
            rec = {"request_id": r.request_id, "role": self.role, "review_ids": list(review_ids), "model": self.model,
                   "provider": self.provider.name, "effort": self.effort, "tier": self.provider.tier,
                   "phase": self.role, "outcome": "failed" if failed else "succeeded",
                   "label_config": self.config_label,
                   "input_tokens": int(r.usage.get("input_tokens", 0) or 0),
                   "cached_input_tokens": int(r.usage.get("cached_input_tokens", 0) or 0),
                   "output_tokens": int(r.usage.get("output_tokens", 0) or 0),
                   "reasoning_tokens": int(r.usage.get("reasoning_tokens", 0) or 0),
                   "local_compute_s": r.usage.get("local_compute_s"), "cost_usd": cost,
                   "latency_s": round(r.latency_s, 3), "attempt": attempt,
                   "error": r.error or (parse_error if r is res else None) or None,
                   "inputs": inputs_note or None, "run_id": self.run_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            self._append(self.run_dir / "calls.jsonl", rec)
            self.calls.append(rec)
        self.ledger.settle(reservation, spent)
        return parsed, res
