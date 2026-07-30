"""
Minimal ReAct-style agent driven by Ollama.

Uses a simple ACTION / FINAL text protocol because small models
are unreliable with native tool calling.
"""

import json
import os
import re
import time

import requests

from .executor import run_python


OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://localhost:11434"
)

OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "llama3.2:1b"
)

MAX_STEPS = 5


SYSTEM_PROMPT = """
You are a data analyst agent.

IMPORTANT:
- Never say hello.
- Never ask the user questions.
- Always follow the required format exactly.
- Use ACTION before FINAL whenever computation is needed.
- Never invent data.

Your response must be ONLY one of these:

THOUGHT: short explanation
ACTION:
<python code>

OR

THOUGHT: short explanation
FINAL:
{"key":"value"}

For ACTION:
Write only Python code after ACTION.
The code must print the result.

For FINAL:
Return only valid JSON.
"""


# Accept:
# ACTION: python
# CODE:
# ```python
# print(...)
# ```
#
# OR:
# ACTION:
# print(...)
#
ACTION_RE = re.compile(
    r"ACTION:\s*(?:python)?\s*(?:CODE:)?\s*"
    r"(?:```(?:python)?\s*)?"
    r"(?P<code>.*?)(?:```|$)",
    re.DOTALL | re.IGNORECASE,
)


# Accept:
# FINAL: {"answer":1}
#
# OR:
# FINAL:
# ```json
# {"answer":1}
# ```
FINAL_RE = re.compile(
    r"FINAL:\s*(?:```json)?\s*"
    r"(?P<final>\{.*?\})"
    r"\s*(?:```)?\s*$",
    re.DOTALL | re.IGNORECASE,
)



def _call_ollama(messages: list[dict]) -> str:

    print("OLLAMA URL:", OLLAMA_URL, flush=True)
    print("OLLAMA MODEL:", OLLAMA_MODEL, flush=True)


    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1
            },
        },
        timeout=120,
    )


    print(
        "OLLAMA STATUS:",
        response.status_code,
        flush=True
    )

    print(
        response.text[:500],
        flush=True
    )


    response.raise_for_status()

    return response.json()["message"]["content"]



def run_agent(question: str, log_fn=None) -> dict:


    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": question
        }
    ]


    for step in range(1, MAX_STEPS + 1):

        raw = _call_ollama(messages)


        messages.append(
            {
                "role": "assistant",
                "content": raw
            }
        )


        if log_fn:
            log_fn(
                {
                    "type": "model_output",
                    "step": step,
                    "content": raw,
                    "ts": time.time()
                }
            )


        # -------------------------
        # Check FINAL
        # -------------------------

        final_match = FINAL_RE.search(raw)

        if final_match:

            final_text = final_match.group("final")


            try:

                answer = json.loads(final_text)


                if log_fn:
                    log_fn(
                        {
                            "type": "final_answer",
                            "step": step,
                            "answer": answer
                        }
                    )


                return answer


            except json.JSONDecodeError as e:


                messages.append(
                    {
                        "role": "user",
                        "content":
                        f"Invalid JSON. Fix FINAL only. Error: {e}"
                    }
                )

                continue



        # -------------------------
        # Check ACTION
        # -------------------------

        action_match = ACTION_RE.search(raw)


        if action_match:


            code = action_match.group("code").strip()


            # avoid empty execution
            if not code:

                messages.append(
                    {
                        "role": "user",
                        "content":
                        "ACTION was empty. Provide python code."
                    }
                )

                continue



            result = run_python(code)


            if log_fn:
                log_fn(
                    {
                        "type": "tool_call",
                        "step": step,
                        "code": code,
                        "result": result
                    }
                )


            observation = (
                "OBSERVATION:\n"
                f"stdout:\n{result['stdout']}\n"
                f"stderr:\n{result['stderr']}\n"
                f"returncode:{result['returncode']}"
            )


            messages.append(
                {
                    "role": "user",
                    "content": observation
                }
            )


            continue



        # -------------------------
        # Format failure
        # -------------------------

        messages.append(
            {
                "role": "user",
                "content":
                """
Follow the format exactly.

Use:

THOUGHT:
ACTION:
python code

or

THOUGHT:
FINAL:
JSON
"""
            }
        )


        if log_fn:

            log_fn(
                {
                    "type": "format_error",
                    "step": step,
                    "raw": raw
                }
            )



    if log_fn:
        log_fn(
            {
                "type": "max_steps_exceeded"
            }
        )


    return {
        "error":
        "agent did not converge to a FINAL answer in time"
    }
