"""Core layer: secrets hygiene, network guard, queue I/O, approval fingerprint, scheduling policy.

Nothing here talks to a network. Stdlib only.
"""
import datetime as dt
import hashlib
import json
import os
import re
import socket
from pathlib import Path

# Policy (ours, stricter than any platform limit). Applied PER PLATFORM.
MAX_POSTS_PER_24H = 2
MIN_GAP_HOURS = 4

VALID_TYPES = ("VIDEO", "IMAGE")
VALID_STATUS = ("draft", "queued", "published", "failed")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

SECRET_PATTERNS = [
    re.compile(r"EAA[A-Za-z0-9]{20,}"),                       # Meta
    re.compile(r"IGAA[A-Za-z0-9_-]{20,}"),                    # Instagram
    re.compile(r"ya29\.[A-Za-z0-9_\-]{20,}"),                 # Google access token
    re.compile(r"1//[A-Za-z0-9_\-]{30,}"),                    # Google refresh token
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}"),                # Google client secret
    re.compile(r"act\.[A-Za-z0-9]{20,}"),                     # TikTok access token
    re.compile(r"(?i)(access_token|refresh_token|client_secret|app_secret|bearer)\s*[=:]\s*[A-Za-z0-9_\-\.]{12,}"),
]
LONG_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{40,}")


class LiveModeDisabled(RuntimeError):
    """Raised by every code path that would need the network or a token."""


class SkeletonAdapter(NotImplementedError):
    """Raised by adapters that only validate (no request flow yet)."""


# --------------------------------------------------------------------------- secrets / network

def find_secrets(text):
    hits = []
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            hits.append(pat.pattern[:30])
    for m in LONG_TOKEN_RE.finditer(text):
        s = m.group(0)
        if re.fullmatch(r"[0-9a-fA-F]+", s):      # sha256 fingerprints are allowed
            continue
        if re.search(r"[A-Za-z]", s) and re.search(r"\d", s):
            hits.append("long-token-like string")
    return hits


def redact(text):
    for pat in SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def block_network():
    """Defence in depth: any attempt to open a connection raises (dry-run only)."""
    def _blocked(*a, **k):
        raise RuntimeError("network is blocked in dry-run mode")
    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked


# --------------------------------------------------------------------------- queue io

def load_queue(path):
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("posts"), list):
        raise ValueError("queue must be an object with a 'posts' list")
    return data, raw


def save_queue(path, data):
    path = Path(path)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if find_secrets(text):
        raise ValueError("refusing to write queue: it contains secret-looking strings")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def media_file(queue_path, item):
    p = Path(str(item.get("media_path", "")))
    return p if p.is_absolute() else (Path(queue_path).resolve().parent / p)


def media_inside_queue_dir(queue_path, item):
    """Media must live under the queue file's folder (blocks ../ and absolute paths to other files, e.g. a
    prompt-injected queue pointing the uploader at ~/.ssh)."""
    base = Path(queue_path).resolve().parent
    try:
        media_file(queue_path, item).resolve().relative_to(base)
        return True
    except ValueError:
        return False


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(queue_path, item):
    """Approval is bound to WHAT goes out and WHERE: type, caption, title, AI flag, targets,
    per-platform options, media bytes. Change any of them and the approval is void."""
    h = hashlib.sha256()
    parts = (
        item.get("type", ""), item.get("caption", ""), item.get("title", ""), str(item.get("public_url")),
        str(item.get("is_ai_generated")),
        json.dumps(sorted(item.get("targets", [])), ensure_ascii=False),
        json.dumps(item.get("options", {}), sort_keys=True, ensure_ascii=False),
        file_sha256(media_file(queue_path, item)),
    )
    for part in parts:
        h.update(part.encode("utf-8") + b"\x00")
    return h.hexdigest()


def parse_time(value):
    if isinstance(value, str) and value[-1:] in ("Z", "z"):
        value = value[:-1] + "+00:00"        # fromisoformat accepts 'Z' only from Python 3.11
    t = dt.datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError("scheduled_at needs an explicit timezone offset, e.g. 2026-11-02T18:00:00+02:00")
    return t


def check_rate_policy(posts):
    """Per-platform cap and gap over draft/queued posts. Returns [(post_id, platform, message)]."""
    by_platform = {}
    for item in posts:
        if not isinstance(item, dict) or item.get("status") not in ("draft", "queued"):
            continue
        try:
            t = parse_time(str(item["scheduled_at"]))
        except (KeyError, ValueError):
            continue
        for plat in item.get("targets", []):
            by_platform.setdefault(plat, []).append((t, str(item.get("id"))))
    errs = []
    for plat, times in by_platform.items():
        times.sort()
        for t, label in times:
            window = [x for x in times if t <= x[0] < t + dt.timedelta(hours=24)]
            if len(window) > MAX_POSTS_PER_24H:
                errs.append((label, plat, f"more than {MAX_POSTS_PER_24H} posts within 24h starting here (policy cap)"))
                break
        for (t1, _), (t2, l2) in zip(times, times[1:]):
            if t2 - t1 < dt.timedelta(hours=MIN_GAP_HOURS):
                errs.append((l2, plat, f"less than {MIN_GAP_HOURS}h after the previous scheduled post"))
    return errs
