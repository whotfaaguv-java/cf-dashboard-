"""
Codeforces friends dashboard.

How to run:
  1. Put your Codeforces handle and your friends' handles in HANDLES below.
  2. In a terminal:  python cf_dashboard.py
  3. Open http://localhost:8000 in your browser.

Needs only Python 3 (nothing to install). Keep the terminal window open while
you want the dashboard to run.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- Settings you can change -------------------------------------------------
HANDLES = ["tourist", "Benq", "jiangly"]  # <-- replace with you + your friends
REFRESH_SECONDS = 60  # how often to ask Codeforces for new data
PORT = int(os.environ.get("PORT", 8000))  # hosting sites set PORT themselves
IST = timezone(timedelta(hours=5, minutes=30))  # "today" is counted in Indian time
# -------------------------------------------------------------------------------

data = {"people": [], "updated": 0, "labels": []}
lock = threading.Lock()
last_call = 0.0


def api(method, **params):
    """Call the Codeforces API (it allows one request per 2 seconds)."""
    global last_call
    wait = 2.1 - (time.time() - last_call)
    if wait > 0:
        time.sleep(wait)
    last_call = time.time()
    url = "https://codeforces.com/api/%s?%s" % (method, urllib.parse.urlencode(params))
    with urllib.request.urlopen(url, timeout=20) as r:
        res = json.load(r)
    if res.get("status") != "OK":
        raise RuntimeError(res.get("comment", "API error"))
    return res["result"]


def analyse(handle, info):
    """Count problems by the day they were FIRST solved (verdict OK)."""
    subs = api("user.status", handle=handle, **{"from": 1, "count": 1000})
    first = {}
    for s in subs:
        if s.get("verdict") != "OK":
            continue
        p = s["problem"]
        key = (p.get("contestId"), p.get("index"), p.get("name"))
        ts = s["creationTimeSeconds"]
        if key not in first or ts < first[key][0]:
            first[key] = (ts, p.get("rating", 0))
    today = datetime.now(IST).date()
    counts, hardest = {}, 0
    for ts, rating in first.values():
        d = datetime.fromtimestamp(ts, IST).date()
        counts[d] = counts.get(d, 0) + 1
        if (today - d).days < 7:
            hardest = max(hardest, rating)
    days = [counts.get(today - timedelta(days=i), 0) for i in range(6, -1, -1)]
    streak = 0
    d = today if today in counts else today - timedelta(days=1)
    while d in counts:
        streak += 1
        d -= timedelta(days=1)
    return {
        "handle": info["handle"],
        "rating": info.get("rating"),
        "maxRating": info.get("maxRating"),
        "rank": info.get("rank", "unrated"),
        "today": days[-1],
        "week": sum(days),
        "days": days,
        "streak": streak,
        "hardest": hardest,
    }


def refresh():
    try:
        infos = {u["handle"].lower(): u for u in api("user.info", handles=";".join(HANDLES))}
    except Exception:
        infos = {}  # one bad handle breaks the batch call, so try them one by one
        for h in HANDLES:
            try:
                infos[h.lower()] = api("user.info", handles=h)[0]
            except Exception:
                pass
    people = []
    for h in HANDLES:
        info = infos.get(h.lower())
        if not info:
            people.append({"handle": h, "error": "Could not load. Check the handle spelling and your internet."})
            continue
        try:
            people.append(analyse(h, info))
        except Exception as e:
            people.append({"handle": info["handle"], "error": "Could not load submissions: %s" % e})
    today = datetime.now(IST).date()
    labels = [(today - timedelta(days=i)).strftime("%a") for i in range(6, -1, -1)]
    with lock:
        data.update(people=people, updated=time.time(), labels=labels)


def loop():
    while True:
        refresh()
        time.sleep(REFRESH_SECONDS)


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codeforces crew</title>
<style>
:root{--bg:#eef2f7;--card:#fff;--ink:#14213d;--mute:#5d6b82;--line:#d6dde8;--acc:31,95,191}
@media (prefers-color-scheme:dark){:root{--bg:#0f1624;--card:#17213a;--ink:#e6ecf7;--mute:#93a1ba;--line:#2a3856;--acc:96,152,255}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "Segoe UI",system-ui,sans-serif;padding:24px 16px}
main{max-width:980px;margin:0 auto}
h1{font-size:28px;margin:0 0 4px}
.sub{color:var(--mute);margin:0 0 20px;font-variant-numeric:tabular-nums}
.wrap{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:720px;font-variant-numeric:tabular-nums}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;color:var(--mute);font-size:14px}
tr:last-child td{border-bottom:0}
.h{font-weight:700;font-size:17px;text-decoration:none}
.big{font-size:20px;font-weight:700}
.days{display:flex;gap:4px}
.d{width:30px;height:30px;border-radius:6px;border:1px solid var(--line);display:grid;place-items:center;font-size:13px}
.err{color:#c0392b}
</style></head><body><main>
<h1>Codeforces crew</h1>
<p class="sub" id="status">Loading first data. This takes a few seconds.</p>
<div class="wrap"><table>
<thead><tr><th>#</th><th>Handle</th><th>Rating</th><th>Best</th><th>Today</th><th>Last 7 days</th>
<th id="dh">Day by day</th><th>Streak</th><th>Hardest this week</th></tr></thead>
<tbody id="rows"></tbody></table></div>
<p class="sub" style="margin-top:12px">A problem counts on the day you first got it accepted. Days follow Indian time.</p>
</main>
<script>
const RC={newbie:'#808080',pupil:'#008000',specialist:'#03a89e',expert:'#3a3aff','candidate master':'#b030b0',
master:'#ff8c00','international master':'#ff8c00',grandmaster:'#e00','international grandmaster':'#e00','legendary grandmaster':'#e00'};
let D=null,got=0;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){try{const r=await fetch('/api/data');D=await r.json();got=Date.now();render()}catch(e){}}
function render(){
  if(!D||!D.updated)return;
  const ok=D.people.filter(p=>!p.error).sort((a,b)=>(b.rating||0)-(a.rating||0));
  const bad=D.people.filter(p=>p.error);
  const lab=D.labels;
  document.getElementById('rows').innerHTML=ok.map((p,i)=>`<tr>
    <td>${i+1}</td>
    <td><a class="h" style="color:${RC[p.rank]||'inherit'}" href="https://codeforces.com/profile/${encodeURIComponent(p.handle)}" target="_blank" rel="noopener">${esc(p.handle)}</a></td>
    <td class="big">${p.rating??'unrated'}</td><td>${p.maxRating??'-'}</td>
    <td class="big">${p.today}</td><td class="big">${p.week}</td>
    <td><div class="days">${p.days.map((n,j)=>`<div class="d" title="${lab[j]}: ${n}" style="${n?`background:rgba(var(--acc),${Math.min(1,.2+n*.2)});color:${n>2?'#fff':'inherit'};border-color:transparent`:'color:var(--mute)'}">${n}</div>`).join('')}</div></td>
    <td>${p.streak} ${p.streak===1?'day':'days'}</td><td>${p.hardest||'-'}</td></tr>`).join('')
    +bad.map(p=>`<tr><td></td><td class="h">${esc(p.handle)}</td><td class="err" colspan="7">${esc(p.error)}</td></tr>`).join('');
  document.getElementById('dh').innerHTML='Day by day<br><span style="font-weight:400">'+lab.join(' ')+'</span>';
}
setInterval(()=>{
  if(!D||!D.updated)return;
  const age=Math.floor((Date.now()-got)/1000+(D.now-D.updated));
  const next=Math.max(0,D.refresh-age);
  document.getElementById('status').textContent='Updated '+age+'s ago. Next refresh in about '+next+'s.';
},1000);
load();setInterval(load,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/data"):
            with lock:
                body = json.dumps(dict(data, refresh=REFRESH_SECONDS, now=time.time())).encode()
            ctype = "application/json"
        else:
            body = PAGE.encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the terminal quiet


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    print("Dashboard running. Open http://localhost:%d in your browser (Ctrl+C to stop)." % PORT)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
