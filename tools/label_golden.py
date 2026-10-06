"""Local web tool for human labeling of the golden 50. No model calls; pipeline predictions are never shown.

If evals/golden/golden_50_ai_draft.csv exists, its AI-drafted labels are pre-filled for the human to
confirm or edit; each saved row records label_source (human_confirmed / human_edited / human_only).

Usage:  python3 tools/label_golden.py      then open http://127.0.0.1:8765
Saves after every review to evals/golden/golden_50_human.csv (resumable).
"""

import csv
import html
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "golden_50_to_label.csv"
OUT = ROOT / "evals" / "golden" / "golden_50_human.csv"
DRAFT = ROOT / "evals" / "golden" / "golden_50_ai_draft.csv"  # AI suggestions; human must confirm/edit
TOPICS = ["access", "usability", "playback", "downloads", "catalog", "billing", "support", "other"]
INTENTS = ["cancellation", "complaint", "request", "praise", "unclear"]
EXTRA = ["alt_topics", "alt_intents", "alt_severities", "ambiguous", "notes", "label_source", "labeled_at"]
CORE = ("topic", "intent", "severity", "sentiment", "evidence_quote", "needs_review")

rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
drafts = {r["review_id"]: r for r in csv.DictReader(DRAFT.open(encoding="utf-8"))} if DRAFT.exists() else {}
BASE_FIELDS = list(rows[0].keys())
FIELDS = BASE_FIELDS + EXTRA


def load_saved():
    if not OUT.exists():
        return {}
    return {r["review_id"]: r for r in csv.DictReader(OUT.open(encoding="utf-8"))}


def save(saved):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:  # keep source order; unlabeled rows keep blank label columns
            w.writerow({**{k: r[k] for k in BASE_FIELDS}, **saved.get(r["review_id"], {})})
    tmp.replace(OUT)


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Golden 50 labeling</title>
<style>
body{font:15px/1.45 -apple-system,system-ui,sans-serif;margin:0;background:#f6f6f4;color:#222}
.wrap{display:grid;grid-template-columns:1fr 380px;gap:20px;max-width:1250px;margin:auto;padding:18px}
.card{background:#fff;border:1px solid #ddd;border-radius:10px;padding:16px 18px}
.review{font-size:18px;white-space:pre-wrap;background:#fffbe8;border:1px solid #eadc9a;padding:14px;border-radius:8px}
.meta{color:#777;font-size:13px;margin:6px 0 12px}
h3{margin:14px 0 6px;font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:#555}
label.opt{display:inline-block;margin:3px 10px 3px 0;cursor:pointer}
input[type=text],textarea{width:100%;box-sizing:border-box;padding:6px;font:inherit}
button{font:inherit;padding:7px 14px;border-radius:7px;border:1px solid #888;background:#fff;cursor:pointer}
button.primary{background:#1db954;color:#fff;border-color:#1db954}
.nav{display:flex;gap:8px;align-items:center;margin-top:14px}
.dots{display:flex;flex-wrap:wrap;gap:4px;margin:8px 0}
.dot{width:22px;height:22px;border-radius:4px;background:#ddd;font-size:11px;text-align:center;line-height:22px;cursor:pointer}
.dot.done{background:#1db954;color:#fff}.dot.cur{outline:2px solid #333}
.err{color:#c00;font-weight:600}.side{font-size:13px}.side td{vertical-align:top;padding:2px 4px}
small{color:#777}
</style></head><body><div class="wrap"><div>
<div class="card"><div><b>Golden 50 — human labels</b> <span id="prog"></span></div><div class="dots" id="dots"></div></div>
<div class="card" style="margin-top:12px">
<div class="meta" id="meta"></div><div id="banner" style="display:none;background:#e8f0ff;border:1px solid #9ab;padding:6px 10px;border-radius:6px;margin-bottom:8px;font-size:13px"><b>AI draft</b> pre-filled — check it, change anything you disagree with, then Save. <span id="dnote"></span></div><div class="review" id="text"></div>
<h3>Topic</h3><div id="topic"></div>
<h3>Intent</h3><div id="intent"></div>
<h3>Severity</h3><div id="severity"></div>
<h3>Sentiment <span id="sentv"></span></h3><input type="range" id="sent" min="-1" max="1" step="0.1" style="width:100%">
<h3>Evidence quote <small>(select text in the review above, then click)</small></h3>
<button onclick="useSel()">Use selection</button> <button onclick="useAll()">Use whole review</button>
<textarea id="quote" rows="2"></textarea>
<h3>Entities <small>(comma-separated features named in the text, e.g. ads, shuffle, lyrics)</small></h3><input type="text" id="entities">
<h3>Flags</h3>
<label class="opt"><input type="checkbox" id="needs_review"> needs_review (ambiguous / missing context)</label>
<label class="opt"><input type="checkbox" id="ambiguous"> ambiguous: other labels also acceptable</label>
<div id="alts" style="display:none;margin-top:6px">
 <small>Also acceptable topics:</small><div id="alt_topics"></div>
 <small>Also acceptable intents:</small><div id="alt_intents"></div>
 <small>Also acceptable severities:</small><div id="alt_severities"></div></div>
<h3>Notes</h3><input type="text" id="notes" placeholder="why (optional, useful for error analysis)">
<div class="nav"><button onclick="go(-1)">← Prev</button><button class="primary" onclick="saveNext()">Save &amp; next →</button><span id="msg"></span></div>
</div></div>
<div class="card side"><b>Definitions (labels-v1)</b>
<table>
<tr><td><b>access</b></td><td>login, signup, password, account access, logged out, hacked account</td></tr>
<tr><td><b>usability</b></td><td>navigation, controls, layout, queue/playlist mgmt, ads, UI changes</td></tr>
<tr><td><b>playback</b></td><td>playback failure, crashes, lag, connection errors, audio quality, battery/data, Bluetooth/car</td></tr>
<tr><td><b>downloads</b></td><td>downloading, saved/offline music, disappearing downloads</td></tr>
<tr><td><b>catalog</b></td><td>missing songs/artists, search, recommendations, lyrics, podcasts</td></tr>
<tr><td><b>billing</b></td><td>price, charges, subscriptions, paywalls, premium entitlement, premium-only controls</td></tr>
<tr><td><b>support</b></td><td>contacting support, support response</td></tr>
<tr><td><b>other</b></td><td>generic praise/criticism, unrelated, nothing specific</td></tr></table>
<p>Most severe problem wins; tie → first mentioned. Positive → first specific praised feature; generic praise → other. Paid-plan mention alone ≠ billing.</p>
<p><b>Intent precedence:</b> cancellation &gt; complaint (incl. mixed) &gt; request &gt; praise &gt; unclear. Bare boycott slogans → unclear.</p>
<p><b>Severity:</b> 1 no problem / praise / unclear / pure request · 2 generic criticism, minor annoyance · 3 degraded/restricted, some use remains · 4 core task blocked · 5 explicit serious financial/privacy/data harm. Stars, anger, price, or wanting to leave alone don't raise severity.</p>
<p><b>Sentiment:</b> −1 very negative … 0 neutral … +1 very positive.</p>
<p>Judge the <b>text</b>, not the stars.</p></div></div>
<script>
const T=__TOPICS__,I=__INTENTS__;let D=[],S={},DR={},cur=0;
function radios(id,vals,name){document.getElementById(id).innerHTML=vals.map(v=>`<label class="opt"><input type="radio" name="${name}" value="${v}"> ${v}</label>`).join('')}
function checks(id,vals,name){document.getElementById(id).innerHTML=vals.map(v=>`<label class="opt"><input type="checkbox" name="${name}" value="${v}"> ${v}</label>`).join('')}
radios('topic',T,'topic');radios('intent',I,'intent');radios('severity',[1,2,3,4,5],'severity');
checks('alt_topics',T,'alt_topics');checks('alt_intents',I,'alt_intents');checks('alt_severities',[1,2,3,4,5],'alt_severities');
const $=id=>document.getElementById(id);
$('ambiguous').onchange=()=>$('alts').style.display=$('ambiguous').checked?'block':'none';
$('sent').oninput=()=>$('sentv').textContent=(+$('sent').value).toFixed(1);
function setR(n,v){document.querySelectorAll(`input[name=${n}]`).forEach(e=>e.checked=(String(e.value)===String(v)))}
function setC(n,vs){document.querySelectorAll(`input[name=${n}]`).forEach(e=>e.checked=vs.includes(String(e.value)))}
function getR(n){const e=document.querySelector(`input[name=${n}]:checked`);return e?e.value:''}
function getC(n){return [...document.querySelectorAll(`input[name=${n}]:checked`)].map(e=>e.value).join('|')}
function useSel(){const s=String(window.getSelection());if(s)$('quote').value=s}
function useAll(){$('quote').value=D[cur].review_text}
function render(){const r=D[cur],isD=!S[r.review_id]&&DR[r.review_id],s=S[r.review_id]||DR[r.review_id]||{};
 $('banner').style.display=isD?'block':'none';$('dnote').textContent=isD&&s.notes?'Draft note: '+s.notes:'';
 $('meta').textContent=`#${cur+1} of ${D.length} · ${r.review_id}`;
 $('text').textContent=r.review_text;
 setR('topic',s.topic||'');setR('intent',s.intent||'');setR('severity',s.severity||'');
 $('sent').value=s.sentiment!==undefined&&s.sentiment!==''?s.sentiment:0;$('sent').oninput();
 $('quote').value=s.evidence_quote||'';$('entities').value=s.entities?JSON.parse(s.entities).join(', '):'';
 $('needs_review').checked=s.needs_review==='true';$('ambiguous').checked=s.ambiguous==='true';$('ambiguous').onchange();
 setC('alt_topics',(s.alt_topics||'').split('|'));setC('alt_intents',(s.alt_intents||'').split('|'));setC('alt_severities',(s.alt_severities||'').split('|'));
 $('notes').value=s.notes||'';$('msg').textContent='';
 const done=Object.keys(S).length;$('prog').textContent=`— ${done}/50 labeled`;
 $('dots').innerHTML=D.map((d,i)=>`<div class="dot ${S[d.review_id]?'done':''} ${i===cur?'cur':''}" onclick="cur=${i};render()">${i+1}</div>`).join('');}
function go(d){cur=Math.max(0,Math.min(D.length-1,cur+d));render()}
async function saveNext(){const r=D[cur];
 const body={review_id:r.review_id,topic:getR('topic'),intent:getR('intent'),severity:getR('severity'),sentiment:(+$('sent').value).toFixed(1),
  evidence_quote:$('quote').value,entities:$('entities').value,needs_review:$('needs_review').checked,ambiguous:$('ambiguous').checked,
  alt_topics:getC('alt_topics'),alt_intents:getC('alt_intents'),alt_severities:getC('alt_severities'),notes:$('notes').value};
 const res=await fetch('/save',{method:'POST',body:JSON.stringify(body)});const j=await res.json();
 if(!j.ok){$('msg').innerHTML='<span class="err">'+j.error+'</span>';return}
 S[r.review_id]=j.saved;if(cur<D.length-1)cur++;render()}
fetch('/data').then(r=>r.json()).then(j=>{D=j.rows;S=j.saved;DR=j.drafts||{};const f=D.findIndex(d=>!S[d.review_id]);cur=f<0?0:f;render()});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/data":
            pub = [{"review_id": r["review_id"], "review_text": r["review_text"]} for r in rows]
            self._send(json.dumps({"rows": pub, "saved": load_saved_labeled(), "drafts": drafts}))
        else:
            self._send(PAGE.replace("__TOPICS__", json.dumps(TOPICS)).replace("__INTENTS__", json.dumps(INTENTS)), "text/html")

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        src = next((r for r in rows if r["review_id"] == b.get("review_id")), None)
        err = None
        if src is None:
            err = "unknown review_id"
        elif b["topic"] not in TOPICS:
            err = "Pick a topic"
        elif b["intent"] not in INTENTS:
            err = "Pick an intent"
        elif b["severity"] not in list("12345"):
            err = "Pick a severity"
        elif not b["evidence_quote"].strip():
            err = "Add an evidence quote"
        elif b["evidence_quote"] not in src["review_text"]:
            err = "Quote must be an exact substring of the review (use 'Use selection')"
        if err:
            return self._send(json.dumps({"ok": False, "error": html.escape(err)}))
        ents = [e.strip() for e in b["entities"].split(",") if e.strip()]
        rec = {"topic": b["topic"], "intent": b["intent"], "severity": b["severity"], "sentiment": b["sentiment"],
               "evidence_quote": b["evidence_quote"], "entities": json.dumps(ents, ensure_ascii=False),
               "needs_review": str(bool(b["needs_review"])).lower(), "ambiguous": str(bool(b["ambiguous"])).lower(),
               "alt_topics": b["alt_topics"] if b["ambiguous"] else "", "alt_intents": b["alt_intents"] if b["ambiguous"] else "",
               "alt_severities": b["alt_severities"] if b["ambiguous"] else "", "notes": b["notes"],
               "label_source": label_source(b["review_id"], b),
               "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        saved = load_saved_labeled()
        saved[b["review_id"]] = rec
        save(saved)
        self._send(json.dumps({"ok": True, "saved": rec}))


def label_source(rid, b):
    """human_confirmed = saved unchanged from the AI draft; human_edited = changed; human_only = no draft."""
    d = drafts.get(rid)
    if not d:
        return "human_only"
    new = {"topic": b["topic"], "intent": b["intent"], "severity": b["severity"], "sentiment": b["sentiment"],
           "evidence_quote": b["evidence_quote"], "needs_review": str(bool(b["needs_review"])).lower()}
    old = {k: d[k] for k in CORE}
    old["sentiment"] = f"{float(old['sentiment']):.1f}"
    return "human_confirmed" if new == old else "human_edited"


def load_saved_labeled():
    return {k: {f: v[f] for f in FIELDS if f not in BASE_FIELDS or f in
                ("topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review")}
            for k, v in load_saved().items() if v.get("topic")}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Golden labeling tool: http://127.0.0.1:{port}  (saves to {OUT.relative_to(ROOT)})  Ctrl+C to stop")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
