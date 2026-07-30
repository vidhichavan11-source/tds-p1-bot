"""
Minimal ReAct-style agent driven by Ollama.

Uses ACTION / FINAL text protocol because small local models
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
    "llama3.2:latest"
)

MAX_STEPS = 5


SYSTEM_PROMPT = """
You are a careful data analyst agent.

Rules:
- Never greet the user.
- Never ask questions.
- Never invent numbers.
- Always compute using Python when calculation is needed.
- Always follow the format exactly.

Every response MUST start with:

THOUGHT:

For computation use:

THOUGHT: short explanation
ACTION:
python code here

The python code MUST print the result.

After receiving OBSERVATION, provide:

THOUGHT: short explanation
FINAL:
{"key":"value"}

FINAL must contain ONLY valid JSON.
"""


# Handles:
#
# ACTION:
# print(5+10)
#
# ACTION: python
# CODE:
# ```python
# print(5+10)
# ```
#
ACTION_RE = re.compile(
    r"ACTION:\s*(?:python)?\s*(?:CODE:\s*)?"
    r"(?:```python\s*)?"
    r"(?P<code>[\s\S]*?)"
    r"(?:```|(?=\nTHOUGHT:)|(?=\nFINAL:)|$)",
    re.IGNORECASE
)


# Handles:
#
# FINAL:
# {"answer":15}
#
# FINAL:
# ```json
# {"answer":15}
# ```
#
FINAL_RE = re.compile(
    r"FINAL:\s*(?:```json\s*)?"
    r"(?P<final>\{[\s\S]*?\})"
    r"\s*(?:```)?",
    re.IGNORECASE
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
                "temperature": 0,
                "num_ctx": 4096,
                "num_predict": 128
            }
        },
        timeout=120
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
        # FINAL handling
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
                        f"""
Your JSON is invalid.

Error:
{e}

Return ONLY:

FINAL:
{{"key":"value"}}
"""
                    }
                )

                continue



        # -------------------------
        # ACTION handling
        # -------------------------

        action_match = ACTION_RE.search(raw)


        if action_match:

            code = action_match.group("code").strip()


            if not code:

                messages.append(
                    {
                        "role": "user",
                        "content":
                        "ACTION was empty. Provide Python code."
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
        # Format recovery
        # -------------------------

        messages.append(
            {
                "role": "user",
                "content":
                """
Follow the required format.

Example:

THOUGHT: Need calculation

ACTION:
print(5+10)

OR

THOUGHT: Done

FINAL:
{"answer":15}
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
