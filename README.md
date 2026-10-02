# mimo2api-native

Self-hosted proxy that turns **Xiaomi MiMo AI Studio** (`aistudio.xiaomimimo.com`) into an **OpenAI + Anthropic compatible API** — with a native (no-Docker) setup guide, a streaming text-quality fix, and real benchmark numbers.

> Fork of / based on upstream **[fly143/mimo2api](https://github.com/fly143/mimo2api)** (MIT) — see [README_UPSTREAM.md](README_UPSTREAM.md) / [README_UPSTREAM_EN.md](README_UPSTREAM_EN.md) for the full upstream feature docs (TTS, ASR, Responses API, function calling internals). This repo = same code + one bugfix + the "run it natively on a laptop" guide.

## What's different from upstream

| Change | Why |
|---|---|
| `app/routes.py`: streaming cleaners no longer `.strip()` each SSE chunk | Upstream stripped whitespace at chunk edges, gluing words together (`"Hithere! Smallcorrectionthough"`). Upstream MiMo sends spaces/newlines at chunk edges (e.g. `' G'` + `'ently'`, whole chunks `'.\n\n'`); stripping per-chunk destroyed them. New `_preserve_chunk_edges` helper cleans the chunk core and re-attaches original edge whitespace. |
| `app/utils.py`: tool/system prompts reframed as `[SESSION CONFIGURATION — injected by the hosting application…]` instead of a fake `system:` role | v2.6 models **detect** the `system:` role spoof inside the user message as a prompt injection and refuse/fight it — emitting malformed `<\|MiMoML\|>` tool calls, ignoring tools, or going off-script. The app-context framing gets clean, parseable tool calls from v2.6-pro. |
| `app/mimo_client.py` + `main.py`: process-level shared httpx pool + 45s upstream keep-alive warmer | Every chat request used to build a fresh `httpx.AsyncClient` → new TCP+TLS handshake each time (~0.2–0.4s TTFT, worse after idle). Now one pooled client (`_pooled_client()`), kept hot by a background warmer (`MIMO_KEEPALIVE=0` disables), closed on shutdown. Measured: remaining TTFT (3.7–12s, high variance) is Xiaomi's inference queue — unaffected by model choice or `reasoning_effort`; the proxy side is now ~0. `main.py` also now imports `asyncio` at module scope (startup handler uses `create_task`). |
| Native run guide (this README) | Upstream pushes Docker; on a laptop a plain venv uses ~80 MB RAM instead of a VM. |

If you sync with upstream: `git checkout app/routes.py` reverts the patch; re-apply by re-reading `_strip_tool_result_blocks` / `_strip_tool_name_prefix` / `_strip_mimo_prefix` here.

## Native setup (no Docker)

```bash
git clone https://github.com/Wraient/mimo2api-native.git
cd mimo2api-native

python3 -m venv venv
./venv/bin/pip install -r requirements.txt

cp config.example.json config.json   # placeholder; real account added below

# pick a random free port and run (bind to localhost!)
PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()")
PORT=$PORT HOST=127.0.0.1 ./venv/bin/python main.py
```

Background variant:

```bash
PORT=$PORT HOST=127.0.0.1 nohup ./venv/bin/python main.py > mimo.log 2>&1 &
```

RAM footprint ≈ 80–90 MB. Stop with `pkill -f 'python main.py'`.

## Getting credentials (the only fiddly part)

The proxy needs 3 cookies from a (free) MiMo Studio login:

| Cookie | Notes |
|---|---|
| `serviceToken` | Shown in DevTools as `xiaomichatbot_serviceToken` — **that's the one** |
| `userId` | numeric |
| `xiaomichatbot_ph` | session identifier |

1. Log in at `https://aistudio.xiaomimimo.com`
2. `F12` → **Application** → **Cookies** → `aistudio.xiaomimimo.com`
3. Copy the three values

Import them (server must be running; default admin login is `admin`/`admin` — **change it in the panel**):

```bash
curl http://127.0.0.1:$PORT/api/account/import-cookie \
  -u admin:admin -H "Content-Type: application/json" \
  -d '{"serviceToken":"...","userId":"...","xiaomichatbot_ph":"..."}'
```

`ok: true` = validated with a live probe message. The admin panel (`http://127.0.0.1:$PORT`) does the same via UI and also accepts **Copy-as-cURL** paste.

> ⚠️ `serviceToken` expires in **~24 h**. When chats start returning 401, re-copy the cookies and re-import. Multiple accounts = round-robin load balancing.

## Using it

Base URL `http://127.0.0.1:$PORT` · API key default `sk-mimo` (set your own in the panel).

```bash
curl http://127.0.0.1:$PORT/v1/chat/completions \
  -H "Authorization: Bearer sk-mimo" -H "Content-Type: application/json" \
  -d '{"model":"mimo-v2.6-pro","messages":[{"role":"user","content":"hello"}]}'
```

- **Models:** `mimo-v2.6-pro` (flagship), `mimo-v2.6-flash` (fast). `GET /v1/models` lists what upstream currently serves.
- **Reasoning:** add `"reasoning_effort": "low" | "medium" | "high"`. Omit = thinking off. Streaming splits it into `delta.reasoning` / `delta.reasoning_content` deltas; non-streaming embeds `<think>...</think>` in `content`.
- **Anthropic clients:** `POST /v1/messages`, header `x-api-key: sk-mimo`.
- **Function calling:** pass a standard OpenAI `tools` array. Without tools, keep `tools_passthrough: false` in the panel — the model occasionally imitates tool-call syntax it has seen in conversations and emits raw `<|MiMoML|...>` markup (upstream's parser only engages when tools are defined).
- **Gotcha:** `-studio` / `-ultraspeed-studio` model IDs from the web UI's localStorage do **not** exist on the API side — you'll get `模型名称错误` (model name error).

## Performance (20 sequential requests, streaming, `mimo-v2.6-pro`)

Measured 2026-10-02 via [bench_pro.py](bench_pro.py) (results in [bench_pro.json](bench_pro.json)); tok/s estimated from chars÷4 since upstream reports 0 completion tokens on streams.

| Metric | Median | Min | Max |
|---|---|---|---|
| Time to first byte token (s) | 7.68 | 3.73 | 29.63 |
| Output tok/s (est.) | 47.8 | 10.0 | 116.5 |
| Total request (s) | 10.28 | 6.80 | 38.50 |

## Security notes

- Bind to `127.0.0.1` (as shown) unless you add auth in front — upstream CORS is fully open.
- `config.json` secrets are Fernet-encrypted at rest; the key lives in `.secret_key` (created on first run, `chmod 600`). **Never commit either file** — both are gitignored here.
- `sessions.json`, `usage.json`, `app/responses.json`, `.anthropic_batches/` are runtime state — gitignored, may contain conversation metadata.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401` / `loginUrl` in errors | `serviceToken` expired → re-import cookies |
| Words glued together (`"Hithere"`) | You're on unpatched upstream — use this repo's `app/routes.py` |
| `模型名称错误` | Model ID doesn't exist upstream (e.g. `-ultraspeed-studio`) |
| Raw `<\|MiMoML\|...>` text in replies | Model hallucinated a tool call with no tools registered; disable `tools_passthrough` / don't send `tools` |
| Port already in use | Re-run the random-port one-liner |
| Admin panel login | default `admin`/`admin` — change it immediately if anything but localhost can reach the service |

## Smoke test

```bash
curl -s http://127.0.0.1:$PORT/v1/models -H "Authorization: Bearer sk-mimo" | head -c 200
```

Returns a JSON model list = server, account discovery, and upstream reachability all working.
