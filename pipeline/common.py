"""Shared helpers: paths, source hashing, CSV reading, atomic writes, JSONL logging.

Source hashing deliberately reuses the course checker's canonical()/row_sha() so
our source_sha256 values are byte-identical to what the grader recomputes.
"""

import csv
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from check_submission import FIELDS, TOPICS, INTENTS, canonical, row_sha, sha as file_sha  # noqa: E402

DATA = ROOT / "data"
WORK = ROOT / "work"          # local state (SQLite, caches) - gitignored
OUTPUTS = ROOT / "outputs"    # saved, committed evidence
DEFAULT_INPUT = DATA / "spotify_reviews_18months.csv"
EXPECTED_SHA256 = "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6"

csv.field_size_limit(sys.maxsize)


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_empty(text):
    return not text.strip()


def read_rows(path):
    """Stream source rows with a real CSV parser (multiline-safe); values are untouched strings."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        missing = [k for k in FIELDS if k not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Input CSV is missing columns: {missing}")
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Malformed CSV row near line {reader.line_num}")
            yield {k: row[k] for k in FIELDS}


def write_json(path, value):
    """Atomic JSON write: temp file + rename, so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def append_jsonl(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
