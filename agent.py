"""
Minimal ReAct-style agent driven by a local Ollama model.

Why not native Ollama tool-calling? Reliability of function-calling on
small local models is inconsistent. A plain text protocol (ACTION /
FINAL) is easier to parse robustly and easier to debug from the logs.

Protocol the model is instructed to follow, one step per model turn:

  THOUGHT: <reasoning, brief>
  ACTION: python
  CODE:
  ```
  <python code, must print() whatever it wants to see>
  ```

or, when it has the final answer:

  THOUGHT: <reasoning, brief>
  FINAL: <one JSON object -- exactly what should be sent back>

The loop stops at MAX_STEPS to avoid runaway local-model chatter.
"""

import json
import os
import re
import time

import requests

from .executor import run_python

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
MAX_STEPS = 8

SYSTEM_PROMPT = """You are a careful data-analyst agent. You answer a single \
data-analysis question by writing and running Python code (pandas/numpy/requests \
are available) to actually compute the answer -- never guess or fabricate numbers.

You may reference public datasets (e.g. MOSPI) by fetching them with requests/pandas \
if the question points at one, or use data embedded directly in the question.

Respond with EXACTLY one of these two forms each turn, nothing else:

THOUGHT: <one or two sentences>
ACTION: python
CODE:
```
<python code that prints whatever you need to see>
```

OR, once you are confident you have the final answer:

THOUGHT: <one or two sentences>
FINAL: <a single JSON object, matching exactly the shape the user's question asked for>

Rules:
- Never skip straight to FINAL without having verified the answer via ACTION at least once,
  unless the question is trivial and needs no computation.
- The FINAL JSON must be valid JSON on a single line, matching the requested keys/shape exactly.
- Do not include any text before THOUGHT or after the closing of ACTION/FINAL.
"""

ACTION_RE = re.compile(
    r"THOUGHT:\s*(?P<thought>.*?)\nACTION:\s*python\s*\nCODE:\s*```(?:python)?\s*\n(?P<code>.*?)```",
    re.DOTALL,
)
FINAL_RE = re.compile(
    r"THOUGHT:\s*(?P<thought>.*?)\nFINAL:\s*(?P<final>\{.*\})\s*$",
    re.DOTALL,
)


def _call_ollama(messages: list[dict]) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def run_agent(question: str, log_fn=None) -> dict:
    """
    Runs the ReAct loop. `log_fn`, if given, is called with a dict for
    every step (model output, tool call, tool result, final answer) so
    the caller can append it to the JSONL run log.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    for step in range(1, MAX_STEPS + 1):
        raw = _call_ollama(messages)
        messages.append({"role": "assistant", "content": raw})

        if log_fn:
            log_fn({"type": "model_output", "step": step, "content": raw,
                     "ts": time.time()})

        final_match = FINAL_RE.search(raw)
        if final_match:
            final_text = final_match.group("final")
            try:
                parsed = json.loads(final_text)
            except json.JSONDecodeError as e:
                # give the model one chance to fix malformed JSON
                messages.append({
                    "role": "user",
                    "content": f"Your FINAL was not valid JSON ({e}). "
                                f"Respond again with a corrected FINAL line only.",
                })
                if log_fn:
                    log_fn({"type": "json_error", "step": step, "error": str(e)})
                continue
            if log_fn:
                log_fn({"type": "final_answer", "step": step, "answer": parsed})
            return parsed

        action_match = ACTION_RE.search(raw)
        if action_match:
            code = action_match.group("code")
            result = run_python(code)
            if log_fn:
                log_fn({"type": "tool_call", "step": step, "code": code,
                        "result": result})
            observation = (
                f"OBSERVATION:\nstdout:\n{result['stdout']}\n"
                f"stderr:\n{result['stderr']}\nreturncode: {result['returncode']}"
            )
            messages.append({"role": "user", "content": observation})
            continue

        # Model didn't follow the protocol -- nudge it back on track.
        messages.append({
            "role": "user",
            "content": "Your response didn't match the required THOUGHT/ACTION "
                        "or THOUGHT/FINAL format. Respond again following the "
                        "format exactly.",
        })
        if log_fn:
            log_fn({"type": "format_error", "step": step, "raw": raw})

    # Ran out of steps -- return a best-effort error shape so the bot
    # still replies with *some* JSON rather than crashing.
    if log_fn:
        log_fn({"type": "max_steps_exceeded"})
    return {"error": "agent did not converge to a FINAL answer in time"}
