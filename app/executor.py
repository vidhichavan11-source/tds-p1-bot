"""
Sandboxed-ish Python execution tool for the agent.

NOT a true security sandbox (no seccomp/containerization) -- it's a
best-effort restriction meant to stop accidental damage, not a hostile
grader. Runs in a subprocess with a timeout so a hung/infinite script
can't stall the bot forever.
"""

import subprocess
import sys
import tempfile
import textwrap
import os

TIMEOUT_SECONDS = 45

# Packages the generated code is allowed to import. Extend as needed.
ALLOWED_TOP_LEVEL_IMPORTS = {
    "pandas", "numpy", "requests", "json", "re", "math", "io",
    "statistics", "datetime", "collections", "itertools", "csv",
    "urllib", "bs4",
}


def _quick_import_check(code: str) -> str | None:
    """Very light static check -- not a real sandbox, just a speed bump."""
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            mod = stripped.split()[1].split(".")[0]
            if mod not in ALLOWED_TOP_LEVEL_IMPORTS:
                return f"Disallowed import: {mod}"
    return None


def run_python(code: str) -> dict:
    """
    Executes `code` in a fresh subprocess. The code should print its
    final result (the agent is instructed to `print(...)` whatever it
    wants to see). Returns dict with stdout, stderr, and returncode.
    """
    problem = _quick_import_check(code)
    if problem:
        return {"stdout": "", "stderr": problem, "returncode": 1}

    wrapped = textwrap.dedent(code)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as f:
        f.write(wrapped)
        path = f.name

    try:
        result = subprocess.run(
            [sys.executable, path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        return {
            "stdout": result.stdout[-4000:],  # keep logs bounded
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Execution timed out after {TIMEOUT_SECONDS}s",
            "returncode": -1,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
