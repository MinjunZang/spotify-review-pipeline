"""Shared output schema, allowed labels, deterministic entity extraction and record validation.

Code owns: allowed values, ID matching, quote membership, entity extraction, record shape.
The model owns: reading the language and choosing labels.
"""

import hashlib
import re

from .common import INTENTS, ROOT, TOPICS

SCHEMA_VERSION = "schema-v1"
LABELS_VERSION = "labels-v1"

SUBTOPICS = {
    "access": ["login_failure", "logged_out", "account_lost_or_hacked", "signup"],
    "usability": ["ads", "ui_navigation", "queue_shuffle_controls", "library_playlist_management", "ui_change"],
    "playback": ["crash_freeze", "playback_stops_or_skips", "connection_error", "audio_quality",
                 "performance_resources", "device_integration"],
    "downloads": ["downloads_missing", "offline_mode", "download_fails"],
    "catalog": ["missing_content", "search", "recommendations", "lyrics", "podcasts"],
    "billing": ["price", "premium_paywall", "charges_refund", "subscription_entitlement"],
    "support": ["support_response"],
    "other": ["general", "unrelated"],
}
ALL_SUBTOPICS = sorted({s for v in SUBTOPICS.values() for s in v})

# Deterministic entity extraction: a fixed feature-term list matched on word boundaries.
ENTITY_TERMS = {
    "ads": r"\bads?\b|\badvert", "premium": r"\bpremium\b", "shuffle": r"\bshuffl", "lyrics": r"\blyric",
    "download": r"\bdownload", "offline": r"\boffline\b", "playlist": r"\bplaylists?\b", "podcast": r"\bpodcast",
    "login": r"\blog ?in\b|\bsign ?in\b|\bpassword\b", "skip": r"\bskip", "search": r"\bsearch",
    "queue": r"\bqueue\b", "bluetooth": r"\bbluetooth\b", "android auto": r"\bandroid auto\b",
    "widget": r"\bwidget", "notification": r"\bnotification", "battery": r"\bbattery\b",
    "crash": r"\bcrash", "update": r"\bupdat", "family plan": r"\bfamily plan\b", "student": r"\bstudent\b",
    "refund": r"\brefund", "customer service": r"\bcustomer (service|support|care)\b", "wrapped": r"\bwrapped\b",
    "smart shuffle": r"\bsmart shuffle\b", "dj": r"\bdj\b", "car": r"\bcar\b", "chromecast": r"\b(chrome)?cast",
}
_ENTITY_RE = {k: re.compile(v, re.I) for k, v in ENTITY_TERMS.items()}


def extract_entities(text):
    return [k for k, rx in _ENTITY_RE.items() if rx.search(text)]


def prompt_text(name):
    return (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def prompt_hash(name):
    return hashlib.sha256(prompt_text(name).encode("utf-8")).hexdigest()[:12]


def label_config(model, effort, prompt_name):
    """Exact-text cache key component: any change here forces new work."""
    return f"{model}|effort={effort}|{prompt_name}@{prompt_hash(prompt_name)}|{SCHEMA_VERSION}"


LABELS = [f"{t}.{sub}" for t, subs in SUBTOPICS.items() for sub in subs]  # "playback.crash_freeze"
SHORT_REVIEW_WORDS = 20  # at or below this, code uses the whole review as the evidence quote


def enrich_json_schema():
    """Compact output (output tokens dominate cost): label = topic.subtopic, short keys."""
    item = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "label", "intent", "sev", "sent", "q", "flag"],
        "properties": {
            "id": {"type": "string"},
            "label": {"type": "string", "enum": LABELS},
            "intent": {"type": "string", "enum": list(INTENTS)},
            "sev": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "sent": {"type": "number"},
            "q": {"type": "string"},
            "flag": {"type": "boolean"},
        },
    }
    return {"type": "object", "additionalProperties": False, "required": ["results"],
            "properties": {"results": {"type": "array", "items": item}}}


def verify_json_schema():
    item = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "topic", "intent", "severity", "sentiment"],
        "properties": {
            "id": {"type": "string"},
            "topic": {"type": "string", "enum": list(TOPICS)},
            "intent": {"type": "string", "enum": list(INTENTS)},
            "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "sentiment": {"type": "number"},
        },
    }
    return {"type": "object", "additionalProperties": False, "required": ["results"],
            "properties": {"results": {"type": "array", "items": item}}}


def resolve_quote(text, quote):
    """Return an exact source substring for the model's quote, or None if it isn't one.

    "*" means the whole review. Only exact matches are accepted, with one tolerance:
    surrounding quotation marks/whitespace the model added are stripped before matching.
    """
    if quote == "*":
        return text if text.strip() else None
    if not isinstance(quote, str):
        return None
    q = quote.strip().strip('"“”\'')
    if q and q in text:
        return q
    return _normalized_find(text, q) if q else None


_EQUIV = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def _normalized_find(text, q):
    """Locate q in text ignoring case, whitespace runs and curly/straight quote differences.

    Returns the ORIGINAL source span (so the quote is still an exact substring), or None.
    """
    def norm(s):
        chars, idx = [], []
        for i, ch in enumerate(s):
            ch = ch.translate(_EQUIV).lower()
            if ch.isspace():
                if chars and chars[-1] == " ":
                    continue
                ch = " "
            chars.append(ch)
            idx.append(i)
        return "".join(chars), idx
    nt, map_t = norm(text)
    nq = norm(q)[0].strip()
    pos = nt.find(nq) if len(nq) >= 3 else -1
    if pos < 0:
        return None
    span = text[map_t[pos]:map_t[pos + len(nq) - 1] + 1]
    return span if span.strip() and span in text else None


def is_short(text):
    return len(text.split()) <= SHORT_REVIEW_WORDS


def validate_item(item, text):
    """Validate one compact model result against the schema. Returns (fields, error)."""
    if not isinstance(item, dict):
        return None, "not_an_object"
    label, intent = item.get("label"), item.get("intent")
    sev, sent, flag = item.get("sev"), item.get("sent"), item.get("flag")
    if not isinstance(label, str) or label.count(".") != 1:
        return None, "invalid_label"
    topic, sub = label.split(".")
    if topic not in TOPICS:
        return None, "invalid_topic"
    if intent not in INTENTS:
        return None, "invalid_intent"
    if type(sev) is not int or not 1 <= sev <= 5:
        return None, "invalid_severity"
    if type(sent) not in (int, float) or not -1 <= sent <= 1:
        return None, "invalid_sentiment"
    if type(flag) is not bool:
        return None, "invalid_needs_review"
    if sub not in SUBTOPICS[topic]:
        sub, flag = SUBTOPICS[topic][0], True  # keep the topic, flag the confusion
    quote = text if is_short(text) and text.strip() else resolve_quote(text, item.get("q"))
    if quote is None:
        return None, "quote_not_in_source"
    return {"topic": topic, "subtopic": sub, "intent": intent, "severity": sev,
            "sentiment": round(float(sent), 2), "evidence_quote": quote,
            "entities": extract_entities(text), "needs_review": flag}, None
