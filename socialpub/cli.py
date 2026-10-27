"""Command line. Dry-run only in v0.1: `run --live` always fails, no network code exists."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import core, flow, service
from .adapters import REGISTRY

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUEUE = ROOT / "queue.json"
LOG_DIR = ROOT / "logs"


def log_line(obj):
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "dry-run.log", "a", encoding="utf-8") as f:
        f.write(core.redact(json.dumps(obj, ensure_ascii=False)) + "\n")


def summarize(item):
    return (f"id={item['id']} type={item['type']} targets={','.join(item['targets'])} at={item['scheduled_at']} "
            f"AI={item['is_ai_generated']}\n  media={item['media_path']}\n  caption={item['caption'][:120]!r}")


def now_from(args):
    return core.parse_time(args.now) if getattr(args, "now", None) else dt.datetime.now(dt.timezone.utc)


def cmd_platforms(_args):
    for name, a in REGISTRY.items():
        mode = "dry-run flow" if a.implemented else "validation only (skeleton)"
        ai = a.ai_field or "caption text"
        print(f"{name:<10} {mode:<28} types={','.join(a.media_types):<12} AI via {ai}")
    return 0


def cmd_validate(args):
    errs, warns = service.validate_queue(args.queue)
    for pid, m in errs:
        print(f"ERROR   [{pid}] {m}")
    for pid, m in warns:
        print(f"warning [{pid}] {m}")
    print(f"validate: {len(errs)} error(s), {len(warns)} warning(s)")
    return 1 if errs else 0


def cmd_plan(args):
    errs, _ = service.validate_queue(args.queue)
    data, _ = core.load_queue(args.queue)
    now = now_from(args)
    print(f"plan (now={now.isoformat()}, policy: max {core.MAX_POSTS_PER_24H}/24h and gap >= {core.MIN_GAP_HOURS}h per platform)")
    rows = []
    for item in data["posts"]:
        try:
            rows.append((core.parse_time(item["scheduled_at"]), item))
        except (KeyError, ValueError):
            continue
    for when, item in sorted(rows, key=lambda r: r[0]):
        try:
            state, reason = service.classify(args.queue, item, now, include_future=False)
        except OSError:
            state, reason = "BLOCKED", "media file missing"
        print(f"- {when.astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%MZ')} {item['id']:<12} "
              f"{item.get('type', ''):<6} -> {','.join(item.get('targets', []))}: {state}: {reason}")
        for plat in item.get("targets", []):
            if plat in REGISTRY:
                print(f"    {plat}: {REGISTRY[plat].plan(item)}")
    if errs:
        print(f"NOTE: queue has {len(errs)} validation error(s); run `validate`.")
    return 1 if errs else 0


def cmd_run(args):
    if args.live:
        print("ERROR: live mode is not implemented in v0.1 (see README, section 'Going live')", file=sys.stderr)
        return 3
    core.block_network()
    errs, _ = service.validate_queue(args.queue)
    if errs:
        for pid, m in errs:
            print(f"ERROR   [{pid}] {m}")
        print("run: refusing to continue, fix validation errors first")
        return 2
    data, _ = core.load_queue(args.queue)
    now = now_from(args)
    print(f"DRY-RUN (no network, nothing is sent) now={now.isoformat()}")
    would = 0
    for item in data["posts"]:
        state, reason = service.classify(args.queue, item, now, args.all)
        print(f"\n[{state}] {summarize(item)}\n  reason: {reason}")
        log_line({"ts": now.isoformat(), "id": item["id"], "state": state, "reason": reason})
        if state != "WOULD_PUBLISH":
            continue
        would += 1
        for plat in item["targets"]:
            adapter = REGISTRY[plat]
            try:
                reqs = adapter.build_requests(item)
            except core.SkeletonAdapter as e:
                print(f"  [{plat}] SKELETON: {e}")
                continue
            transport = flow.DryRunTransport()
            outcome, _trace = flow.simulate(reqs, transport)
            for r in reqs:
                shown = core.redact(flow.dumps(flow.public_view(r)))
                print(f"  >> [{plat}] {shown}")
                log_line({"ts": now.isoformat(), "id": item["id"], "platform": plat, "dry_run_request": flow.public_view(r)})
            print(f"  [{plat}] simulated flow against mock answers: {outcome}")
    print(f"\nDRY-RUN done: {would} post(s) would be published, 0 requests sent")
    return 0


def cmd_approve(args):
    data, _ = core.load_queue(args.queue)
    item = next((p for p in data["posts"] if p.get("id") == args.id), None)
    if item is None:
        print(f"ERROR: no post with id {args.id}", file=sys.stderr)
        return 2
    if args.revoke:
        item["approved"] = False
        item.pop("approved_at", None)
        item.pop("approved_fingerprint", None)
        core.save_queue(args.queue, data)
        print(f"approval revoked for {args.id}")
        return 0
    e, _ = service.validate_item(args.queue, item)
    if e:
        print("ERROR: post is not valid, cannot approve: " + "; ".join(e), file=sys.stderr)
        return 2
    print("You are approving this post for ALL listed targets (it will still need a YES at live publish time):")
    print(summarize(item))
    if not sys.stdin.isatty():
        print("ERROR: approve needs an interactive terminal (type YES). Refusing.", file=sys.stderr)
        return 2
    if input("Type YES to approve: ").strip() != "YES":
        print("not approved")
        return 1
    service.apply_approval(args.queue, data, item)
    print(f"approved {args.id}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="publish.py", description="social-publisher v0.1 (dry-run only)")
    p.add_argument("--queue", default=str(DEFAULT_QUEUE))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("platforms")
    sub.add_parser("validate")
    pp = sub.add_parser("plan")
    pp.add_argument("--now", help="ISO time with offset (testing)")
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true", default=True, help="default and only working mode")
    r.add_argument("--live", action="store_true", help="not implemented: always errors")
    r.add_argument("--all", action="store_true", help="include approved posts that are not due yet")
    r.add_argument("--now", help="ISO time with offset (testing)")
    a = sub.add_parser("approve")
    a.add_argument("id")
    a.add_argument("--revoke", action="store_true")
    args = p.parse_args(argv)
    return {"platforms": cmd_platforms, "validate": cmd_validate, "plan": cmd_plan,
            "run": cmd_run, "approve": cmd_approve}[args.cmd](args)
