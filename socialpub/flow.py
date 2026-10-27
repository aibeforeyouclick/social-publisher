"""Flow runner + transports.

A "flow" is the ordered list of request dicts an adapter builds. `simulate` walks it through a Transport.
Only DryRunTransport exists: it answers from the `mock` data embedded in each step, opens no socket and
needs no token. LiveTransport is a stub that raises, so there is no code path that could send anything.

Step keys: step, method, url, headers, body | body_file, mock (list of canned responses; one per poll),
capture {PLACEHOLDER: dotted.path}, guard {path, max_exclusive}, poll {until:{path:value}, fail_on:[..], max}.
"""
import copy
import json
import re

from .core import LiveModeDisabled

PLACEHOLDER = re.compile(r"<([A-Z0-9_]+)>")


def dig(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def substitute(value, variables):
    if isinstance(value, str):
        return PLACEHOLDER.sub(lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    return value


def public_view(step):
    """What is shown/logged: the request without the embedded mock answers."""
    return {k: v for k, v in step.items() if k != "mock"}


class LiveTransport:
    """Stub. v0.1 contains no HTTP code at all."""
    def send(self, request):
        raise LiveModeDisabled("live transport does not exist in v0.1")


class DryRunTransport:
    """Records requests, answers from the step's `mock` list. No socket, no token."""
    def __init__(self):
        self.sent = []
        self._counters = {}

    def send(self, request):
        self.sent.append(request)
        key = request["step"]
        mocks = request.get("mock") or [{}]
        i = self._counters.get(key, 0)
        self._counters[key] = i + 1
        return copy.deepcopy(mocks[min(i, len(mocks) - 1)])


def simulate(requests, transport):
    """Run a flow. Returns (outcome, trace). outcome: 'ok' | 'stopped:<why>'. Publishing steps only run
    after every guard/poll before them passed (e.g. IG publishes only on status_code FINISHED)."""
    variables, trace = {}, []
    for step in requests:
        req = substitute(copy.deepcopy(step), variables)
        poll = req.get("poll")
        attempts = poll["max"] if poll else 1
        resp = None
        for n in range(attempts):
            resp = transport.send(req)
            trace.append((req["step"], n + 1, public_view({"response": resp})["response"]))
            if not poll:
                break
            status = dig(resp, next(iter(poll["until"])))
            if status in poll.get("fail_on", []):
                return f"stopped:{req['step']} reported {status}", trace
            if status == next(iter(poll["until"].values())):
                break
        else:
            return f"stopped:{req['step']} did not finish in {attempts} polls", trace
        guard = req.get("guard")
        if guard and dig(resp, guard["path"]) >= guard["max_exclusive"]:
            return f"stopped:{req['step']} quota guard", trace
        for var, path in req.get("capture", {}).items():
            variables[var] = dig(resp, path)
    return "ok", trace


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)
