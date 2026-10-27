"""Queue validation, approval state and the dry-run decision, shared by the CLI and the tests."""
import datetime as dt

from . import core, media as media_mod
from .adapters import REGISTRY


def inspect_media(qpath, item):
    """(media_dict | None, error_or_None). None media with no error means ffprobe is missing."""
    f = core.media_file(qpath, item)
    try:
        return media_mod.inspect(f, item.get("type")), None
    except (media_mod.MediaError, OSError) as e:
        return None, str(e)


def validate_item(qpath, item):
    errs, warns = [], []
    pid = item.get("id")
    if not isinstance(pid, str) or not core.ID_RE.match(pid):
        errs.append("id must match [A-Za-z0-9_-]{1,40}")
    if item.get("type") not in core.VALID_TYPES:
        errs.append(f"type must be one of {core.VALID_TYPES}")
    if item.get("status") not in core.VALID_STATUS:
        errs.append(f"status must be one of {core.VALID_STATUS}")
    if not isinstance(item.get("approved"), bool):
        errs.append("approved must be true/false")
    ai = item.get("is_ai_generated")
    if not isinstance(ai, bool):
        errs.append("is_ai_generated is mandatory (true/false)")
    elif ai is False and not str(item.get("ai_false_reason", "")).strip():
        errs.append("is_ai_generated=false needs a non-empty ai_false_reason")
    try:
        core.parse_time(str(item.get("scheduled_at", "")))
    except ValueError as e:
        errs.append(f"scheduled_at: {e}")
    cap = item.get("caption")
    if not isinstance(cap, str) or not cap.strip():
        errs.append("caption is required")
    targets = item.get("targets")
    if not isinstance(targets, list) or not targets:
        errs.append("targets must be a non-empty list of platforms")
        targets = []
    elif len(set(targets)) != len(targets):
        errs.append("duplicate platform in targets")
    unknown = [t for t in targets if t not in REGISTRY]
    if unknown:
        errs.append(f"unknown platform(s): {unknown} (known: {sorted(REGISTRY)})")
    if not isinstance(item.get("options", {}), dict):
        errs.append("options must be an object")

    media = None
    if not item.get("media_path"):
        errs.append("media_path is required")
    elif not core.media_inside_queue_dir(qpath, item):
        errs.append("media_path must be inside the queue file's folder")
    elif not core.media_file(qpath, item).is_file():
        errs.append(f"media file not found: {item.get('media_path')}")
    elif item.get("type") in core.VALID_TYPES:
        media, merr = inspect_media(qpath, item)
        if merr:
            errs.append(merr)
        elif media is None:
            errs.append("ffprobe not found: video codec/duration/fps cannot be verified")

    if not errs:                      # platform checks need a well-formed post and readable media
        for plat in targets:
            e, w = [], []
            REGISTRY[plat].check_ai_disclosure(item, e)
            REGISTRY[plat].validate(item, media, e, w)
            errs += [f"[{plat}] {m}" for m in e]
            warns += [f"[{plat}] {m}" for m in w]
    return errs, warns


def validate_queue(qpath):
    """Return (errors, warnings) as lists of (post_id_or_'queue', message)."""
    errs, warns = [], []
    try:
        data, raw = core.load_queue(qpath)
    except (OSError, ValueError) as e:
        return [("queue", f"cannot load queue: {e}")], []
    for hit in core.find_secrets(raw):
        errs.append(("queue", f"secret-looking content in queue file ({hit})"))
    seen = set()
    for i, item in enumerate(data["posts"]):
        pid = item.get("id") if isinstance(item, dict) else None
        label = pid if isinstance(pid, str) else f"#{i}"
        if not isinstance(item, dict):
            errs.append((label, "post must be an object"))
            continue
        if pid in seen:
            errs.append((label, "duplicate id"))
        seen.add(pid)
        e, w = validate_item(qpath, item)
        errs += [(label, m) for m in e]
        warns += [(label, m) for m in w]
    errs += [(label, f"[{plat}] {m}") for label, plat, m in core.check_rate_policy(data["posts"])]
    return errs, warns


def classify(qpath, item, now, include_future):
    if item["status"] != "queued":
        return "SKIPPED", f"status is {item['status']} (only 'queued' runs)"
    if not item["approved"]:
        return "SKIPPED", "not approved"
    if item.get("approved_fingerprint") != core.fingerprint(qpath, item):
        return "BLOCKED", "content/targets/options changed since approval (or no fingerprint): approve again"
    if core.parse_time(item["scheduled_at"]) > now and not include_future:
        return "NOT_DUE", f"scheduled for {item['scheduled_at']}"
    return "WOULD_PUBLISH", "approved, valid, due"


def apply_approval(qpath, data, item):
    item["approved"] = True
    item["approved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    item["approved_fingerprint"] = core.fingerprint(qpath, item)
    core.save_queue(qpath, data)
