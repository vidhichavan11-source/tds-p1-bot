"""
Sandboxed-ish Python execution tool for the agent.

NOT a true security sandbox (no seccomp/containerization) -- it's a
best-effort restriction meant to stop accidental damage, not a hostile
grader. Runs in a subprocess with a timeout so a hung/infinite script
can't stall the bot forever.
"""

import os
import subprocess
import sys
import tempfile
import textwrap

TIMEOUT_SECONDS = 45

# Packages the generated code is allowed to import.
ALLOWED_TOP_LEVEL_IMPORTS = {
    "pandas",
    "numpy",
    "requests",
    "json",
    "re",
    "math",
    "io",
    "statistics",
    "datetime",
    "collections",
    "itertools",
    "csv",
    "urllib",
    "bs4",
}


def _quick_import_check(code: str) -> str | None:
    """Very light static check -- not a real sandbox."""
    for line in code.splitlines():
        stripped = line.strip()

        if stripped.startswith("import "):
            mod = stripped.split()[1].split(".")[0]
            if mod not in ALLOWED_TOP_LEVEL_IMPORTS:
                return f"Disallowed import: {mod}"

        elif stripped.startswith("from "):
            mod = stripped.split()[1].split(".")[0]
            if mod not in ALLOWED_TOP_LEVEL_IMPORTS:
                return f"Disallowed import: {mod}"

    return None


def run_python(code: str) -> dict:
    """
    Execute Python code in a fresh subprocess.
    The generated code is expected to print its answer.
    """

    print("========== PYTHON EXECUTOR ==========", flush=True)
    print(code, flush=True)
    print("=====================================", flush=True)

    problem = _quick_import_check(code)

    if problem:
        return {
            "stdout": "",
            "stderr": problem,
            "returncode": 1,
        }

    wrapped = textwrap.dedent(code)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(wrapped)
        script_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )

        print("PYTHON FINISHED", flush=True)
        print("Return code:", result.returncode, flush=True)
        print("STDOUT:", result.stdout, flush=True)
        print("STDERR:", result.stderr, flush=True)

        return {
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        print("PYTHON TIMED OUT", flush=True)

        return {
            "stdout": "",
            "stderr": f"Execution timed out after {TIMEOUT_SECONDS} seconds.",
            "returncode": -1,
        }

    except Exception as e:
        print("PYTHON EXECUTION FAILED", flush=True)
        print(str(e), flush=True)

        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
        }

    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass
