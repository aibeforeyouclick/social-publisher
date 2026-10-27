import ast
import contextlib
import datetime as dt
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from socialpub import cli, core, flow, service, secrets_provider  # noqa: E402
from socialpub.adapters import REGISTRY  # noqa: E402

DEMO_NOW = "2026-10-24T20:00:00+03:00"
FAKE_TOKEN = "EAA" + "Z9" * 20  # fake, only proves tokens never leak

GOOD_VIDEO = {"kind": "VIDEO", "size": 1_000_000, "ext": ".mp4", "faststart": True, "vcodec": "h264",
              "pix_fmt": "yuv420p", "field_order": "progressive", "width": 1080, "height": 1920, "fps": 30.0,
              "duration": 20.0, "bitrate": 5_000_000, "has_audio": True, "acodec": "aac",
              "sample_rate": 48000, "channels": 2}


def post(**over):
    item = {"id": "p1", "type": "IMAGE", "media_path": "demo_image.jpg", "caption": "hello #x",
            "scheduled_at": "2026-11-02T16:00:00+02:00", "targets": ["instagram"], "status": "queued",
            "is_ai_generated": True, "approved": False}
    item.update(over)
    return item


def video_post(**over):
    base = dict(id="v1", type="VIDEO", media_path="demo_reel.mp4", targets=["instagram"])
    base.update(over)
    return post(**base)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for name in ("demo_image.jpg", "demo_reel.mp4"):
            shutil.copy(ROOT / "samples" / name, self.tmp / name)
        self.q = self.tmp / "queue.json"
        self._log = cli.LOG_DIR
        cli.LOG_DIR = self.tmp / "logs"
        self._net = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)

    def tearDown(self):
        cli.LOG_DIR = self._log
        (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo) = self._net
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, posts):
        self.q.write_text(json.dumps({"posts": posts}), encoding="utf-8")

    def errors(self):
        return [m for _, m in service.validate_queue(self.q)[0]]

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--queue", str(self.q), *argv])
        return code, out.getvalue(), err.getvalue()


class ValidateTests(Tmp):
    def test_shipped_sample_queue_is_valid(self):
        self.assertEqual(service.validate_queue(ROOT / "queue.json")[0], [])

    def test_good_image_and_reel(self):
        self.write([post(), video_post(scheduled_at="2026-11-03T16:00:00+02:00")])
        self.assertEqual(self.errors(), [])

    def test_ai_flag_mandatory_and_false_needs_reason(self):
        item = post()
        del item["is_ai_generated"]
        self.write([item])
        self.assertTrue(any("is_ai_generated is mandatory" in e for e in self.errors()))
        self.write([post(is_ai_generated=False)])
        self.assertTrue(any("ai_false_reason" in e for e in self.errors()))

    def test_targets_required_known_unique(self):
        for bad, needle in (([], "non-empty"), (["myspace"], "unknown platform"), (["instagram", "instagram"], "duplicate")):
            self.write([post(targets=bad)])
            self.assertTrue(any(needle in e for e in self.errors()), bad)

    def test_instagram_caption_limits(self):
        self.write([post(caption="x" * 2201)])
        self.assertTrue(any("2200" in e for e in self.errors()))
        self.write([post(caption=" ".join(f"#t{i}" for i in range(31)))])
        self.assertTrue(any("hashtags" in e for e in self.errors()))

    def test_z_suffix_is_accepted_like_plus_zero(self):
        self.assertEqual(core.parse_time("2026-11-02T16:00:00Z"), core.parse_time("2026-11-02T16:00:00+00:00"))
        self.assertEqual(core.parse_time("2026-11-02T16:00:00z").utcoffset(), dt.timedelta(0))
        self.write([post(scheduled_at="2026-11-02T16:00:00Z")])
        self.assertEqual(self.errors(), [])
        with self.assertRaises(ValueError):
            core.parse_time("2026-11-02T16:00:00")

    def test_naive_time_and_missing_media(self):
        self.write([post(scheduled_at="2026-11-02T16:00:00"), post(id="p2", media_path="nope.jpg")])
        errs = self.errors()
        self.assertTrue(any("timezone" in e for e in errs))
        self.assertTrue(any("not found" in e for e in errs))

    def test_media_outside_queue_folder_is_rejected(self):
        outside = self.tmp.parent / "outside.jpg"
        shutil.copy(self.tmp / "demo_image.jpg", outside)
        try:
            for path in (str(outside), "../outside.jpg"):
                self.write([post(media_path=path)])
                self.assertTrue(any("inside the queue" in e for e in self.errors()), path)
        finally:
            outside.unlink()

    def test_rate_policy_is_per_platform(self):
        base = dt.datetime(2026, 11, 2, 8, 0, tzinfo=dt.timezone.utc)
        three = [post(id=f"p{i}", scheduled_at=(base + dt.timedelta(hours=5 * i)).isoformat()) for i in range(3)]
        self.write(three)
        self.assertTrue(any("policy cap" in e for e in self.errors()))
        # same times but spread over different platforms: each platform stays under the cap
        spread = [post(id="a", targets=["instagram"], scheduled_at=base.isoformat()),
                  post(id="b", targets=["youtube"], scheduled_at=(base + dt.timedelta(hours=1)).isoformat(),
                       options={"youtube": {"made_for_kids": False}}, type="VIDEO", media_path="demo_reel.mp4")]
        self.write(spread)
        self.assertFalse(any("4h" in e or "policy cap" in e for e in self.errors()))
        close = [post(id="a", scheduled_at=base.isoformat()),
                 post(id="b", scheduled_at=(base + dt.timedelta(hours=2)).isoformat())]
        self.write(close)
        self.assertTrue(any("4h" in e for e in self.errors()))

    def test_real_reel_passes_instagram_and_spec_violations_fail(self):
        errs, warns = [], []
        REGISTRY["instagram"].validate(video_post(), GOOD_VIDEO, errs, warns)
        self.assertEqual(errs, [])
        bad = dict(GOOD_VIDEO, vcodec="vp9", pix_fmt="yuv444p", width=2560, height=1440, fps=120.0, duration=2.0,
                   bitrate=90_000_000, acodec="mp3", sample_rate=96000, channels=6, faststart=False)
        errs = []
        REGISTRY["instagram"].validate(video_post(), bad, errs, [])
        joined = " | ".join(errs)
        for needle in ("moov", "video codec", "pixel format", "width 2560", "frame rate", "duration", "bitrate",
                       "audio codec", "sample rate", "mono or stereo"):
            self.assertIn(needle, joined)

    def test_real_demo_reel_inspected_by_ffprobe(self):
        m, err = service.inspect_media(self.q, video_post())
        self.assertIsNone(err)
        self.assertIsNotNone(m, "ffprobe required for this test")
        errs = []
        REGISTRY["instagram"].validate(video_post(), m, errs, [])
        self.assertEqual(errs, [])

    def test_youtube_rules(self):
        yt = REGISTRY["youtube"]
        errs, warns = [], []
        yt.validate(video_post(targets=["youtube"]), GOOD_VIDEO, errs, warns)
        self.assertTrue(any("made_for_kids" in e for e in errs))     # must be explicit
        ok = video_post(targets=["youtube"], options={"youtube": {"made_for_kids": False}})
        errs = []
        yt.validate(ok, GOOD_VIDEO, errs, [])
        self.assertEqual(errs, [])
        errs = []
        yt.validate(video_post(targets=["youtube"], type="IMAGE", options={"youtube": {"made_for_kids": False}}),
                    None, errs, [])
        self.assertTrue(any("not supported" in e for e in errs))
        errs = []
        yt.validate(video_post(targets=["youtube"], options={"youtube": {"made_for_kids": False, "privacy": "secret"}}),
                    GOOD_VIDEO, errs, [])
        self.assertTrue(any("privacy" in e for e in errs))

    def test_tiktok_unaudited_cannot_go_public_and_ai_needs_caption(self):
        tt = REGISTRY["tiktok"]
        base = video_post(targets=["tiktok"], caption="clip AI-generated",
                          options={"tiktok": {"privacy_level": "PUBLIC_TO_EVERYONE"}})
        errs = []
        tt.validate(base, GOOD_VIDEO, errs, [])
        self.assertTrue(any("unaudited" in e for e in errs))
        errs = []
        tt.validate(video_post(targets=["tiktok"]), GOOD_VIDEO, errs, [])
        self.assertTrue(any("privacy_level" in e for e in errs))
        # caption-based AI disclosure enforced by service for platforms without an API flag
        self.write([video_post(targets=["tiktok"], caption="no disclosure here",
                               options={"tiktok": {"privacy_level": "SELF_ONLY"}})])
        self.assertTrue(any("no API flag" in e for e in self.errors()))

    def test_skeleton_limits(self):
        errs = []
        REGISTRY["facebook"].validate(video_post(targets=["facebook"]), dict(GOOD_VIDEO, duration=120.0), errs, [])
        self.assertTrue(any("3-90" in e for e in errs))
        errs = []
        REGISTRY["linkedin"].validate(video_post(targets=["linkedin"], caption="AI-generated"), GOOD_VIDEO, errs, [])
        self.assertTrue(any("urn:li" in e for e in errs))
        errs, warns = [], []
        REGISTRY["x"].validate(video_post(targets=["x"], caption="see https://e.com AI-generated"), GOOD_VIDEO, errs, warns)
        self.assertTrue(any("$0.20" in w for w in warns))


class SecretTests(Tmp):
    def test_find_and_redact(self):
        for s in (FAKE_TOKEN, "ya29." + "a1" * 15, "act." + "Ab1" * 10, "access_" + "token=abcdefghijklmnop",
                  "refresh_" + "token: abcdefghijklmnop"):
            self.assertTrue(core.find_secrets(s), s)
            self.assertNotIn(s.split("=")[-1].split(": ")[-1], core.redact(s))
        self.assertEqual(core.find_secrets("a" * 64), [])  # sha256-like hex is a fingerprint

    def test_queue_with_secret_fails_and_is_not_saved(self):
        self.write([post(caption="Bearer " + FAKE_TOKEN)])
        self.assertTrue(any("secret-looking" in e for e in self.errors()))
        with self.assertRaises(ValueError):
            core.save_queue(self.q, {"posts": [post(caption=FAKE_TOKEN)]})

    def test_secret_wrapper_never_reveals(self):
        s = secrets_provider.Secret(FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, repr(s) + str(s) + f"{s}" + json.dumps({"k": str(s)}))

    def test_token_provider_env_and_bitwarden_without_running_either(self):
        with mock.patch.dict(os.environ, {"SOCIALPUB_YOUTUBE_TOKEN": FAKE_TOKEN}):
            self.assertEqual(secrets_provider.get_token("youtube").reveal(), FAKE_TOKEN)
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(secrets_provider.shutil, "which", return_value="bw"), \
                mock.patch.object(secrets_provider.subprocess, "run",
                                  return_value=mock.Mock(returncode=0, stdout=FAKE_TOKEN + "\n")) as run:
            self.assertEqual(secrets_provider.get_token("x", bw_item="item").reveal(), FAKE_TOKEN)
            self.assertEqual(run.call_args[0][0][1:3], ["get", "password"])
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            secrets_provider.get_token("instagram")

    def test_token_never_printed_or_logged_in_dry_run(self):
        self.demo()
        out = io.StringIO()
        env = {name: FAKE_TOKEN for name in secrets_provider.ENV_NAMES.values()}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            cli.main(["--queue", str(self.q), "validate"])
            cli.main(["--queue", str(self.q), "run", "--now", DEMO_NOW])
        self.assertNotIn(FAKE_TOKEN, out.getvalue())
        self.assertNotIn(FAKE_TOKEN, (cli.LOG_DIR / "dry-run.log").read_text(encoding="utf-8"))
        self.assertNotIn(FAKE_TOKEN, self.q.read_text(encoding="utf-8"))

    def demo(self):
        shutil.copy(ROOT / "samples" / "queue.demo-approved.json", self.q)


class ApprovalAndRunTests(Tmp):
    demo = SecretTests.demo

    def test_unapproved_is_skipped(self):
        self.write([post(scheduled_at="2026-10-24T10:00:00+03:00")])
        code, out, _ = self.cli("run", "--now", DEMO_NOW)
        self.assertEqual(code, 0)
        self.assertIn("[SKIPPED]", out)
        self.assertIn("0 post(s) would be published", out)

    def test_demo_queue_dry_run_all_platform_flows(self):
        self.demo()
        code, out, _ = self.cli("run", "--now", DEMO_NOW)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("[WOULD_PUBLISH]"), 2)
        self.assertIn("0 requests sent", out)
        self.assertIn("[youtube] simulated flow against mock answers: ok", out)
        self.assertIn("[instagram] simulated flow against mock answers: ok", out)
        self.assertIn("[tiktok] SKELETON", out)

    def test_not_due_needs_all_flag(self):
        self.demo()
        _, out, _ = self.cli("run", "--now", "2026-10-24T09:00:00+03:00")
        self.assertEqual(out.count("[NOT_DUE]"), 2)
        _, out, _ = self.cli("run", "--all", "--now", "2026-10-24T09:00:00+03:00")
        self.assertEqual(out.count("[WOULD_PUBLISH]"), 2)

    def test_changing_content_targets_or_options_invalidates_approval(self):
        for key, value in (("caption", "edited. AI-generated"),
                           ("targets", ["instagram"]), ("public_url", "https://evil.example/other.mp4"),
                           ("options", {"youtube": {"privacy": "public", "made_for_kids": False},
                                        "tiktok": {"privacy_level": "SELF_ONLY"}})):
            self.demo()
            data = json.loads(self.q.read_text(encoding="utf-8"))
            data["posts"][0][key] = value
            self.q.write_text(json.dumps(data), encoding="utf-8")
            _, out, _ = self.cli("run", "--now", DEMO_NOW)
            self.assertIn("[BLOCKED]", out, key)

    def test_approve_refuses_without_tty_and_does_not_change_queue(self):
        self.write([post()])
        before = self.q.read_text(encoding="utf-8")
        with mock.patch.object(sys, "stdin", io.StringIO("YES\n")):
            code, _, err = self.cli("approve", "p1")
        self.assertEqual(code, 2)
        self.assertIn("interactive", err)
        self.assertEqual(self.q.read_text(encoding="utf-8"), before)

    def test_approve_needs_exact_yes_then_revoke(self):
        self.write([post()])
        tty = mock.Mock()
        tty.isatty.return_value = True
        with mock.patch.object(sys, "stdin", tty), mock.patch("builtins.input", return_value="yes"):
            self.assertEqual(self.cli("approve", "p1")[0], 1)
        self.assertFalse(json.loads(self.q.read_text())["posts"][0]["approved"])
        with mock.patch.object(sys, "stdin", tty), mock.patch("builtins.input", return_value="YES"):
            self.assertEqual(self.cli("approve", "p1")[0], 0)
        saved = json.loads(self.q.read_text())["posts"][0]
        self.assertTrue(saved["approved"])
        self.assertEqual(len(saved["approved_fingerprint"]), 64)
        self.assertEqual(self.cli("approve", "p1", "--revoke")[0], 0)
        self.assertFalse(json.loads(self.q.read_text())["posts"][0]["approved"])

    def test_dry_run_does_not_touch_queue_or_open_sockets(self):
        self.demo()
        before = self.q.read_bytes()
        opened, real = [], socket.socket

        class Spy(real):
            def __init__(self, *a, **k):
                opened.append(a)
                super().__init__(*a, **k)

        with mock.patch.object(socket, "socket", Spy):
            self.cli("run", "--now", DEMO_NOW)
        self.assertEqual(opened, [])
        self.assertEqual(self.q.read_bytes(), before)
        with self.assertRaises(RuntimeError):
            socket.create_connection(("example.com", 80))

    def test_live_mode_is_not_implemented_anywhere(self):
        self.demo()
        code, out, err = self.cli("run", "--live")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("not implemented", err)
        for adapter in REGISTRY.values():
            with self.assertRaises(core.LiveModeDisabled):
                adapter.publish(post())
        with self.assertRaises(core.LiveModeDisabled):
            flow.LiveTransport().send({})

    def test_validation_errors_block_run(self):
        self.write([post(is_ai_generated=None)])
        code, out, _ = self.cli("run", "--now", DEMO_NOW)
        self.assertEqual(code, 2)
        self.assertIn("refusing", out)

    def test_platforms_command_lists_all_six(self):
        _, out, _ = self.cli("platforms")
        for name in ("instagram", "youtube", "facebook", "tiktok", "linkedin", "x"):
            self.assertIn(name, out)


class FlowTests(unittest.TestCase):
    def test_instagram_flow_shape_and_publish_only_after_finished(self):
        reqs = REGISTRY["instagram"].build_requests(video_post(public_url="https://example.com/a.mp4"))
        self.assertEqual([r["step"].split()[0] for r in reqs], ["0", "1", "2", "3"])
        self.assertEqual(reqs[1]["url"], "https://graph.instagram.com/v26.0/<IG_USER_ID>/media")
        self.assertEqual(reqs[1]["body"]["video_url"], "https://example.com/a.mp4")
        self.assertIs(reqs[1]["body"]["is_ai_generated"], True)
        t = flow.DryRunTransport()
        outcome, trace = flow.simulate(reqs, t)
        self.assertEqual(outcome, "ok")
        polls = [r for r in t.sent if r["step"].startswith("2")]
        self.assertEqual(len(polls), 2)                                # IN_PROGRESS, then FINISHED
        self.assertEqual(t.sent[-1]["body"], {"creation_id": "MOCK_CONTAINER_1"})  # id captured from step 1

    def test_flow_stops_on_error_expired_timeout_and_quota(self):
        reqs = REGISTRY["instagram"].build_requests(video_post())
        for status in ("ERROR", "EXPIRED"):
            r = json.loads(json.dumps(reqs))
            r[2]["mock"] = [{"status_code": status}]
            t = flow.DryRunTransport()
            outcome, _ = flow.simulate(r, t)
            self.assertTrue(outcome.startswith("stopped"), outcome)
            self.assertFalse(any(x["step"].startswith("3") for x in t.sent), "must not publish")
        r = json.loads(json.dumps(reqs))
        r[2]["mock"] = [{"status_code": "IN_PROGRESS"}]
        t = flow.DryRunTransport()
        outcome, _ = flow.simulate(r, t)
        self.assertIn("did not finish", outcome)
        self.assertEqual(len([x for x in t.sent if x["step"].startswith("2")]), 5)
        r = json.loads(json.dumps(reqs))
        r[0]["mock"] = [{"data": [{"quota_usage": 2}]}]
        t = flow.DryRunTransport()
        self.assertIn("quota guard", flow.simulate(r, t)[0])
        self.assertEqual(len(t.sent), 1)

    def test_youtube_flow(self):
        ok = video_post(targets=["youtube"], options={"youtube": {"made_for_kids": False}})
        reqs = REGISTRY["youtube"].build_requests(ok)
        body = reqs[0]["body"]
        self.assertEqual(body["status"]["privacyStatus"], "private")          # safe default
        self.assertIs(body["status"]["containsSyntheticMedia"], True)
        self.assertIn("#Shorts", body["snippet"]["description"])
        self.assertTrue(reqs[0]["url"].startswith("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable"))
        t = flow.DryRunTransport()
        self.assertEqual(flow.simulate(reqs, t)[0], "ok")
        self.assertEqual(t.sent[1]["url"], "https://upload.invalid/mock-session")

    def test_requests_hold_placeholders_only_and_no_forbidden_endpoints(self):
        ok = video_post(targets=["youtube"], options={"youtube": {"made_for_kids": False}})
        blob = json.dumps([flow.public_view(r) for p in ("instagram", "youtube")
                           for r in REGISTRY[p].build_requests(ok)])
        self.assertIn("Bearer <ACCESS_TOKEN>", blob)
        self.assertEqual(core.find_secrets(blob), [])
        for forbidden in ("/comments", "/messages", "/follow", "/ads", "/insights", "/me?"):
            self.assertNotIn(forbidden, blob)

    def test_skeletons_raise_skeleton_error(self):
        for name in ("facebook", "tiktok", "linkedin", "x"):
            with self.assertRaises(core.SkeletonAdapter):
                REGISTRY[name].build_requests(post())


class StaticSafetyTests(unittest.TestCase):
    BANNED = {"urllib", "http", "requests", "ftplib", "smtplib", "xmlrpc", "telnetlib", "ssl", "asyncio",
              "aiohttp", "httpx", "websocket", "websockets", "webbrowser", "ctypes"}

    def sources(self):
        return list((ROOT / "socialpub").rglob("*.py")) + [ROOT / "publish.py"]

    def test_no_network_modules_imported_anywhere(self):
        for f in self.sources():
            tree = ast.parse(f.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add((node.module or "").split(".")[0])
            self.assertEqual(imported & self.BANNED, set(), f.name)

    def test_only_two_modules_may_spawn_processes(self):
        users = {f.name for f in self.sources() if "subprocess" in f.read_text(encoding="utf-8")}
        self.assertEqual(users, {"media.py", "secrets_provider.py"})

    def test_environment_only_read_in_secrets_provider(self):
        users = {f.name for f in self.sources() if "os.environ" in f.read_text(encoding="utf-8")}
        self.assertEqual(users, {"secrets_provider.py"})

    def test_no_eval_exec_or_token_writes(self):
        for f in self.sources():
            src = f.read_text(encoding="utf-8")
            for bad in ("eval(", "exec(", "os.system(", "shell=True", "pickle"):
                self.assertNotIn(bad, src, f"{bad} in {f.name}")

    def test_dry_run_never_imports_secrets_provider(self):
        for name in ("cli.py", "service.py", "flow.py", "core.py"):
            self.assertNotIn("secrets_provider", (ROOT / "socialpub" / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
