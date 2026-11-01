# How the README screenshots were captured

These are real captures of the running application — no mockups, no edited
images. They were taken on Windows 11 with a headless Chromium browser
(Microsoft Edge) driven over the Chrome DevTools Protocol.

## Runtime state used (isolated, not the developer's real data)

The screenshot session ran the backend against a throwaway data directory so
no personal documents or conversations could leak into the images:

```bat
:: from backend/ (with the venv active)
set DATA_DIR=%TEMP%\shots-data
set EMBEDDING_PROVIDER=sentence-transformers
set LLM_PROVIDER=ollama
set OLLAMA_CHAT_MODEL=llama3.2:1b
set SERVE_FRONTEND=1
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Then a small sample text file (`space-handbook.txt` — planetary facts) was
uploaded through the real `POST /api/documents` endpoint, so the library,
retrieval and citations in the shots all reflect genuine app behavior.
Ollama served `llama3.2:1b` locally for the chat answers.

## Capture tooling

A ~200-line Node script (Node 18+ built-ins only) talks to the Chromium
DevTools Protocol over WebSocket:

1. Launch Edge headless:
   ```bat
   "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
     --headless=new --remote-debugging-port=9222 ^
     --user-data-dir=%TEMP%\edge-profile --no-first-run --disable-gpu ^
     --window-size=1600,1000 about:blank
   ```
2. Connect to `ws://127.0.0.1:9222/devtools/page/<id>` and drive the page with
   `Page.navigate`, `Emulation.setDeviceMetricsOverride` (1600×1000,
   deviceScaleFactor 1.35), `Input.dispatchMouseEvent` (click/hover),
   `Input.insertText` (typing) and `Page.captureScreenshot` (PNG).
3. `Runtime.evaluate` is used for waits — e.g. wait until the health badge is
   `.connection-badge--online`, wait until the streaming stop-button is gone
   and a `[data-testid=source-card]` exists before shooting the chat.

## Shot list

| File | State captured |
|------|----------------|
| `home.png` | Fresh load of `http://127.0.0.1:8000/`: library shows the ingested doc, sidebar empty, `Connected` badge |
| `upload.png` | Same view, mouse hovering the dropzone (hover state visible) |
| `chat-citations.png` | Question sent through the real UI, streaming finished, first source card clicked open (snippet exposed) |
| `conversations.png` | Same conversation, mouse hovering the sidebar item so the rename/delete buttons are revealed |
| `production-mode.png` | After a full reload in the same session, the persisted conversation re-opened — demonstrates `SERVE_FRONTEND=1` production serving + SQLite-backed history |

The answer text visible in `chat-citations.png` ("The Earth travels around
the Sun once every 365.256 days") was produced at capture time by
`llama3.2:1b` from the uploaded document — it is not scripted output. It is
normal for small local models to produce wording differences between runs.
