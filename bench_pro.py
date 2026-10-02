import json, time, urllib.request, statistics as s

PORT = open('.port').read().strip()
PROMPT = "Explain why the sky is blue in about 100 words."
N = 20
LOG = open("bench_pro.log", "w")

def log(msg):
    print(msg, flush=True)
    LOG.write(msg + "\n"); LOG.flush()

def one(i):
    body = {"model": "mimo-v2.6-pro",
            "messages": [{"role": "user", "content": PROMPT}],
            "stream": True, "max_tokens": 150,
            "stream_options": {"include_usage": True}}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer sk-mimo"})
    t0 = time.time(); first = None; usage = {}; chunks = 0; content_chars = 0
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            for line in r:
                line = line.decode(errors="replace").strip()
                if not line.startswith("data:"): continue
                data = line[5:].strip()
                if data == "[DONE]": break
                try: d = json.loads(data)
                except Exception: continue
                delta = (d.get("choices") or [{}])[0].get("delta", {})
                c = delta.get("content") or ""
                if c:
                    if first is None: first = time.time() - t0
                    chunks += 1; content_chars += len(c)
                if d.get("usage"): usage = d["usage"]
        total = time.time() - t0
        ct = usage.get("completion_tokens", 0)
        if not ct: ct = content_chars // 4  # fallback estimate
        gen = total - (first or 0)
        row = {"i": i, "ttbt": round(first or -1, 3),
               "tok_s": round(ct/gen, 2) if gen > 0 else -1,
               "ct": ct, "ct_reported": usage.get("completion_tokens", 0),
               "total_s": round(total, 2), "ok": True}
    except Exception as e:
        row = {"i": i, "ok": False, "err": str(e)[:120]}
    log(f"req {i:02d}: " + json.dumps(row))
    return row

t_start = time.time()
rows = [one(i) for i in range(1, N+1)]
ok = [r for r in rows if r.get("ok")]
tt = sorted(r["ttbt"] for r in ok if r["ttbt"] > 0)
ts = sorted(r["tok_s"] for r in ok if r["tok_s"] > 0)
tot = sorted(r["total_s"] for r in ok)
def med(v): return round(s.median(v), 3) if v else "NA"
summary = {"ok": f"{len(ok)}/{N}", "wall_s": round(time.time()-t_start, 1),
  "ttbt": {"med": med(tt), "min": min(tt) if tt else "NA", "max": max(tt) if tt else "NA"},
  "tok_s": {"med": med(ts), "min": min(ts) if ts else "NA", "max": max(ts) if ts else "NA"},
  "total_s_med": med(tot)}
log("SUMMARY: " + json.dumps(summary))
json.dump({"rows": rows, "summary": summary}, open("bench_pro.json", "w"), indent=1)
