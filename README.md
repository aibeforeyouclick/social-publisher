# social-publisher — dry-run: does not publish

A self-hosted, approval-gated **publishing planner** for accounts you own: Instagram, YouTube Shorts, Facebook Pages, TikTok, LinkedIn, X behind one interface. Open source (MIT). **Your tokens stay with you**: no hosted service, no third party holding credentials, no MCP server.

> **Status: v0.1, dry-run only. This tool does not publish anything.** The code contains no HTTP client and no tokens. `run` prints and logs the API calls that *would* be made and simulates the multi-step flows against **mock answers written by the author** (not against any platform). `run --live` exits with an error. Live publishing is a future, separate step, and nothing here has been tested against a real account.

| Platform | v0.1 |
|---|---|
| Instagram (Instagram Login) | dry-run flow: quota check → container → poll `FINISHED` → publish |
| YouTube Shorts | dry-run flow: resumable upload, `private` by default |
| Facebook Pages, TikTok, LinkedIn, X | validation of documented limits only; no request flow yet |

## Requirements
- Python 3.10+ (developed and tested locally on 3.14; CI runs 3.10 and 3.12 on Ubuntu and Windows).
- **No third-party packages.** `ffprobe` (part of FFmpeg) must be on `PATH` to inspect videos; without it, video posts fail validation.
- A future live mode would also use the Bitwarden CLI (`bw`) if you choose that token source.

## Use
```
python -I publish.py platforms
python -I publish.py validate                  # queue + media vs platform limits (offline)
python -I publish.py plan                      # what would go out, when, what blocks it
python -I publish.py run                       # dry-run (default and only mode)
python -I publish.py approve <id>              # approve one post: interactive terminal, type YES
python -I publish.py approve <id> --revoke
python -I -m unittest discover -s tests        # 39 tests, no network
```
`--queue <file>` selects another queue (media must live in that file's folder). Log: `logs/dry-run.log` (git-ignored, redacted).

Queue format: see `queue.json` (draft posts) and `samples/queue.demo-approved.json` (approved, due posts). Each post has `targets` (platforms), optional per-platform `options`, `is_ai_generated` (mandatory), `approved`, and `approved_fingerprint` written by `approve`.

## Samples
Everything in `samples/` and the demo `queue.json` is fictional. `demo_reel.mp4` (5 s, 1080x1920, H.264/AAC, container tag `encoder=Lavf`) is a synthetic FFmpeg test pattern (colour bars with a moving line and a checkerboard), no third-party footage or audio. `demo_image.jpg` is a plain single-colour 1080x1350 JPEG. Any FFmpeg-generated clip of that format works as a replacement.

## Safety model
- Approval is bound to a SHA-256 of caption, title, AI flag, targets, options, public URL and media bytes. Edit anything → approve again.
- AI content is always labelled: platform field where it exists, caption disclosure where it does not.
- Per-platform defaults: 2 posts / 24 h and ≥4 h gap (constants in `socialpub/core.py`; you can change them, which is on you, see below). No comments/DMs/follows/ads/analytics code at all.
- Secrets: scanner on queue load/save, redacted logs, tokens only from an environment variable or Bitwarden CLI at request time (future), never stored.
- Network: banned imports are checked by a test; sockets are blocked at runtime in dry-run.

## Terms & responsible use
Using a platform's API is governed by that platform's terms, which this project does **not** replace and which can change. Summary of what the official pages said when read on 2026-10-24 (AI-assisted summaries of the pages; read the originals before any live use):
- **Meta (Instagram/Facebook):** [Platform Terms](https://developers.facebook.com/terms/) and [Developer Policies](https://developers.facebook.com/devpolicy/). Keep tokens and app secrets protected, use platform data only for permitted purposes, don't spam or mislead, obtain consent before publishing for people, App Review/compliance applies, Meta may suspend apps. The Developer Policies' bot/inauthentic-behavior rules are written for messaging; they contain no dedicated feed-posting automation rule.
- **YouTube:** [API Services Terms](https://developers.google.com/youtube/terms/api-services-terms-of-service). Don't circumvent quotas, keep API data protected, show the required upload notices and "Made for Kids" handling if you build an upload UI, publish a privacy policy if you serve other users. The separate [Developer Policies](https://developers.google.com/youtube/terms/developer-policies) were **not** read.
- **TikTok:** [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) and [Developer Terms](https://www.tiktok.com/legal/tik-tok-developer-terms-of-service?lang=en) (terms text not read). Unaudited clients can only post privately; user must consent and choose privacy manually. The guidelines name "a utility tool to help upload contents to the account(s) you or your team manages" as **not acceptable** for audit, so this tool should not be expected to qualify for public TikTok posting.
- **X:** [Developer Agreement and Policy / automation rules](https://developer.x.com/en/developer-terms/automation) — **could not be read** (page blocked at fetch time). Posting is pay-per-use.
- LinkedIn and Facebook-Pages-specific terms: **not read**.

What this means for you: you are responsible for your accounts, your app registrations, the content you publish (including AI disclosure and copyright), and for staying within each platform's rules. The tool is built to make mass or spam posting hard (human approval per post, low caps, no engagement features) and is not meant for bulk or multi-account operation. The built-in caps are defaults, not a legal safeguard.

Docs: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/PLATFORM-MATRIX.md`](docs/PLATFORM-MATRIX.md) (what was verified against official docs and what was not) · [`THREAT-MODEL.md`](THREAT-MODEL.md)

## Going live (not implemented)
Out of scope for v0.1. Before it could exist: your own platform developer apps and account tokens; a decision on temporary public media hosting for Instagram (see `docs/ARCHITECTURE.md`); token storage and refresh handling; an HTTP transport with an account check, a second confirmation at publish time and a served-bytes hash check; each platform's current terms (above) and, for TikTok, its audit rules.

Not affiliated with or endorsed by Meta, Google/YouTube, TikTok, LinkedIn or X.

License: MIT (see `LICENSE`).
