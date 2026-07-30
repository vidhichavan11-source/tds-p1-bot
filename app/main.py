"""
Telegram webhook receiver for the TDS Project 1 data-analyst bot.

Flow per incoming message:
  1. Telegram POSTs the update to /webhook/<TELEGRAM_WEBHOOK_SECRET>
  2. We ack Telegram immediately (200 OK) and process in the background
     -- Telegram webhooks time out fast, and the local Ollama round-trip
     can take a while.
  3. Background task: build conversation context (handles the
     multi-turn case), run the agent, log every step to the JSONL run
     log in your GitHub repo, then send the final JSON reply back to
     the same chat via sendMessage.

Deploy this on Render as a web service. Set the Telegram webhook to:
  https://<your-render-app>.onrender.com/webhook/<TELEGRAM_WEBHOOK_SECRET>
"""

import json
import os
import time
from collections import defaultdict

import requests
from fastapi import BackgroundTasks, FastAPI, Request

from .agent import run_agent
from .github_logger import append_log_line, log_url

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Multi-turn handling: buffer recent messages per chat, use the whole
# buffered thread as context, answer the latest one. Threads older than
# THREAD_WINDOW_SECONDS are treated as unrelated / stale.
THREAD_WINDOW_SECONDS = 120
_chat_history = defaultdict(list)  # chat_id -> list[(ts, text)]

app = FastAPI()


def _safe_log(entry: dict) -> None:
    entry.setdefault("ts", time.time())
    try:
        append_log_line(entry)
    except Exception as e:  # noqa: BLE001 -- logging must never crash the bot
        print(f"[log_line failed] {e}")


def _send_telegram_message(chat_id: int, text: str) -> None:
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )


def _build_context(chat_id: int, text: str) -> str:
    now = time.time()
    history = _chat_history[chat_id]
    history.append((now, text))
    # drop stale messages outside the window
    history[:] = [(ts, t) for ts, t in history if now - ts <= THREAD_WINDOW_SECONDS]

    if len(history) == 1:
        return text

    joined = "\n".join(f"- {t}" for _, t in history[:-1])
    return (
        f"Earlier messages in this thread:\n{joined}\n\n"
        f"Now answer this message:\n{text}"
    )


def _process_update(chat_id: int, message_text: str) -> None:
    _safe_log({"type": "incoming_message", "chat_id": chat_id, "text": message_text})

    question_with_context = _build_context(chat_id, message_text)

    try:
        answer = run_agent(
            question_with_context,
            log_fn=lambda entry: _safe_log({**entry, "chat_id": chat_id}),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()

        _send_telegram_message(chat_id, f"ERROR: {e}")
        return

    if isinstance(answer, dict):
        answer["log_url"] = log_url()
    else:
        answer = {"answer": answer, "log_url": log_url()}

    reply_text = json.dumps(answer, ensure_ascii=False)
    _safe_log({"type": "reply_sent", "chat_id": chat_id, "reply": answer})
    _send_telegram_message(chat_id, reply_text)

@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request, background_tasks: BackgroundTasks):
    if secret != WEBHOOK_SECRET:
        return {"ok": False}

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message or "text" not in message:
        return {"ok": True}  # ignore non-text updates

    chat_id = message["chat"]["id"]
    text = message["text"]

    background_tasks.add_task(_process_update, chat_id, text)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
