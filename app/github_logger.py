"""
Appends run-log lines to logs/run.jsonl inside your public GitHub repo
using the GitHub Contents API (no local git binary needed -- works
fine on Render).

Requires:
  GITHUB_TOKEN   - a fine-grained PAT with "Contents: Read and write"
                   on the target repo
  GITHUB_REPO    - "your-username/your-repo"
  GITHUB_BRANCH  - defaults to "main"
  LOG_PATH       - defaults to "logs/run.jsonl"

The public log_url to hand back to the grader is the raw URL:
  https://raw.githubusercontent.com/<repo>/<branch>/<LOG_PATH>
"""

import base64
import json
import os
import time

import requests

GITHUB_API = "https://api.github.com"


def _cfg():
    repo = os.environ["GITHUB_REPO"]
    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = os.environ.get("LOG_PATH", "logs/run.jsonl")
    token = os.environ["GITHUB_TOKEN"]
    return repo, branch, path, token


def log_url() -> str:
    repo, branch, path, _ = _cfg()
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def _get_current_file(repo, branch, path, token):
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    resp = requests.get(
        url,
        params={"ref": branch},
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    if resp.status_code == 404:
        return "", None
    resp.raise_for_status()


def append_log_line(entry: dict, retries: int = 3) -> None:
    """Appends one JSON-serializable dict as a new line in the log file."""
    repo, branch, path, token = _cfg()
    line = json.dumps(entry, ensure_ascii=False)

    for attempt in range(retries):
        current, sha = _get_current_file(repo, branch, path, token)
        new_content = (current + line + "\n") if current else (line + "\n")
        b64 = base64.b64encode(new_content.encode("utf-8")).decode("ascii")

        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        body = {
            "message": f"log: append run entry ({entry.get('type', 'event')})",
            "content": b64,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        resp = requests.put(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return
        if resp.status_code == 409:
            # sha conflict (concurrent write) -- retry with backoff
            time.sleep(0.5 * (attempt + 1))
            continue
        resp.raise_for_status()

    raise RuntimeError("Failed to append log line after retries (409 conflicts)")
