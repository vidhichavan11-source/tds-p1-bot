# TDS Project 1 — Data Analyst Telegram Bot

A ReAct-style LLM agent that answers data-analysis questions sent over
Telegram, replying with exactly one JSON object per the grading spec.

## Architecture

```
Telegram (grader) --webhook--> Render (FastAPI app)
                                     |
                                     |  ReAct loop (THOUGHT/ACTION/FINAL)
                                     v
                        Local Ollama <--Cloudflare tunnel-- your Windows PC
                                     |
                                     v
                        python code execution (pandas/requests) per step
                                     |
                                     v
                     JSONL log appended to your GitHub repo (Contents API)
                                     |
                                     v
                        Final JSON reply sent back via Telegram sendMessage
```

Because the LLM is local, **your PC + Ollama + tunnel must stay running
for the entire grading window**, not just while you're testing.

## 1. Install Ollama and pull a model (Windows)

```powershell
winget install Ollama.Ollama
ollama pull qwen2.5:7b-instruct
ollama serve
```

Leave `ollama serve` running in its own terminal. Default port: `11434`.

## 2. Expose Ollama publicly via Cloudflare Tunnel (Windows)

You've done this before for TDS microservices -- same pattern:

```powershell
cloudflared.exe tunnel --url http://localhost:11434 --http-host-header="localhost:11434"
```

Copy the `https://xxxxx.trycloudflare.com` URL it prints -- that's your
`OLLAMA_URL`.

> Quick tunnels restart with a new URL if the process dies. For
> anything longer than a test session, consider a named Cloudflare
> Tunnel (persistent hostname) instead of the quick `--url` tunnel.

## 3. Create the Telegram bot

1. Message `@BotFather` on Telegram, run `/newbot`, choose a name and a
   username ending in `bot`.
2. Save the token it gives you as `TELEGRAM_BOT_TOKEN`.

## 4. Create a GitHub PAT for logging

GitHub → Settings → Developer settings → Fine-grained tokens → generate
new token, scoped to your bot's repo, with **Contents: Read and write**
permission. Save it as `GITHUB_TOKEN`.

## 5. Configure environment variables

Copy `.env.example` to `.env` and fill in:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (any random string)
- `OLLAMA_URL` (your Cloudflare tunnel URL)
- `GITHUB_TOKEN`, `GITHUB_REPO` (e.g. `vidhichavan11-source/tds-p1-bot`)

## 6. Deploy to Render

1. Push this repo to GitHub (public).
2. On Render: New → Web Service → connect the repo → it will pick up
   `render.yaml` automatically.
3. Set the env vars marked `sync: false` in the Render dashboard
   (Render doesn't accept secrets via `render.yaml` directly).
4. Deploy. Note your service URL, e.g.
   `https://tds-p1-telegram-bot.onrender.com`.

## 7. Point the Telegram webhook at Render

Run once from anywhere with internet (PowerShell):

```powershell
$TOKEN = "your-bot-token"
$SECRET = "your-webhook-secret"
$URL = "https://tds-p1-telegram-bot.onrender.com/webhook/$SECRET"
Invoke-RestMethod -Uri "https://api.telegram.org/bot$TOKEN/setWebhook?url=$URL"
```

You should get back `{"ok":true,"result":true,...}`.

## 8. Test locally against the official grading pipeline

```powershell
git clone https://github.com/Jivraj-18/tds-p1-t2-2026-telegram-bot
cd tds-p1-t2-2026-telegram-bot
# follow its README to point it at your bot username and run evals/questions.json
```

Add your own test questions to `evals/questions.json` there before
running -- the graded questions are separate and not visible to you.

## 9. Sanity-check the log

```powershell
Invoke-WebRequest "https://raw.githubusercontent.com/<you>/<repo>/main/logs/run.jsonl" -OutFile check.jsonl
Get-Content check.jsonl | Select-Object -Last 5
```

Each line should be one JSON object (model output, tool call, or final
answer).

## Known limitations / things to watch

- **Ollama tool reliability**: small local models sometimes drift from
  the THOUGHT/ACTION/FINAL format. `agent.py` nudges the model back on
  track when this happens, but if you see this a lot in the logs,
  try a stronger local model (`llama3.1:8b-instruct`,
  `qwen2.5:14b-instruct` if your RAM allows) or increase `MAX_STEPS`.
- **RAM**: running Ollama + the model + Render's health checks +
  anything else on your 8GB machine can get tight. Close Docker/WSL2
  workloads you don't need during grading.
- **Switching to a hosted API later**: if the local-machine-uptime risk
  becomes a problem, swap `agent.py`'s `_call_ollama` for a call to
  Anthropic/OpenAI's chat completions endpoint -- the ReAct loop and
  logging stay the same, only the model call changes.
