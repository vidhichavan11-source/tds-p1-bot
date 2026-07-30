"""
Telegram webhook receiver for the TDS Project 1 data-analyst bot.

Flow:
1. Telegram POSTs update to /webhook/<TELEGRAM_WEBHOOK_SECRET>
2. Immediately return 200 OK
3. Process message in background
4. Run agent
5. Log execution
6. Send response back to Telegram
"""

import json
import os
import time
from collections import defaultdict

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from .agent import run_agent
from .github_logger import append_log_line, log_url


TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# Store recent conversation history per chat
THREAD_WINDOW_SECONDS = 120
_chat_history = defaultdict(list)


app = FastAPI(
    title="TDS Telegram Data Analyst Bot"
)


# -----------------------------
# Health / status endpoints
# -----------------------------

@app.get("/")
async def root():
    return {
        "status": "running",
        "service": "telegram-bot"
    }


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }


# -----------------------------
# Logging helper
# -----------------------------

def _safe_log(entry: dict):
    entry.setdefault("ts", time.time())

    try:
        append_log_line(entry)

    except Exception as e:
        print(f"[LOG ERROR] {e}")


# -----------------------------
# Telegram sender
# -----------------------------

def _send_telegram_message(chat_id: int, text: str):

    try:
        response = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text
            },
            timeout=15
        )

        print(
            "Telegram response:",
            response.status_code,
            response.text
        )

    except Exception as e:
        print(f"[Telegram send failed] {e}")


# -----------------------------
# Conversation context
# -----------------------------

def _build_context(chat_id: int, text: str):

    now = time.time()

    history = _chat_history[chat_id]

    history.append(
        (now, text)
    )

    history[:] = [
        (ts, msg)
        for ts, msg in history
        if now - ts <= THREAD_WINDOW_SECONDS
    ]


    if len(history) == 1:
        return text


    previous = "\n".join(
        f"- {msg}"
        for _, msg in history[:-1]
    )


    return (
        "Earlier messages in this thread:\n"
        f"{previous}\n\n"
        "Now answer this message:\n"
        f"{text}"
    )


# -----------------------------
# Background processing
# -----------------------------

def _process_update(chat_id: int, message_text: str):

    print("=== PROCESS START ===")
    print("Chat:", chat_id)
    print("Message:", message_text)


    _safe_log(
        {
            "type": "incoming_message",
            "chat_id": chat_id,
            "text": message_text
        }
    )


    question = _build_context(
        chat_id,
        message_text
    )


    try:

        print("Calling run_agent...")


        answer = run_agent(
            question,
            log_fn=lambda entry:
                _safe_log(
                    {
                        **entry,
                        "chat_id": chat_id
                    }
                )
        )


        print("run_agent finished")


    except Exception as e:

        import traceback
        traceback.print_exc()


        _send_telegram_message(
            chat_id,
            f"ERROR: {str(e)}"
        )

        return



    if isinstance(answer, dict):

        answer["log_url"] = log_url()

    else:

        answer = {
            "answer": answer,
            "log_url": log_url()
        }



    reply = json.dumps(
        answer,
        ensure_ascii=False
    )


    _safe_log(
        {
            "type": "reply_sent",
            "chat_id": chat_id,
            "reply": answer
        }
    )


    _send_telegram_message(
        chat_id,
        reply
    )


    print("=== PROCESS END ===")



# -----------------------------
# Telegram webhook
# -----------------------------

@app.post("/webhook/{secret}")
async def telegram_webhook(
        secret: str,
        request: Request,
        background_tasks: BackgroundTasks
):


    if secret != WEBHOOK_SECRET:

        raise HTTPException(
            status_code=403,
            detail="Invalid webhook secret"
        )


    update = await request.json()


    message = (
        update.get("message")
        or update.get("edited_message")
    )


    if not message:

        return {
            "ok": True
        }


    if "text" not in message:

        return {
            "ok": True
        }


    chat_id = message["chat"]["id"]

    text = message["text"]


    print("=== WEBHOOK RECEIVED ===")
    print("Chat ID:", chat_id)
    print("Message:", text)


    background_tasks.add_task(
        _process_update,
        chat_id,
        text
    )


    print("=== BACKGROUND TASK ADDED ===")


    return {
        "ok": True
    }
