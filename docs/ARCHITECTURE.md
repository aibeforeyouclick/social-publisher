# Architecture (v0.1, dry-run)

```
queue.json ──► service.validate ──► classify (status, approval, fingerprint, due) ──► per target: adapter.build_requests
   ▲                 │                                                                      │
   │            core (secrets scan,                                                  flow.simulate
 approve (TTY,    policy cap/gap,                                                    (DryRunTransport,
 "YES", bound     fingerprint)                                                       mock answers, no socket)
 to content)
```

## Layers
| Layer | File | Role |
|---|---|---|
| core | `socialpub/core.py` | secret patterns + redaction, runtime network block, queue I/O, approval fingerprint, per-platform cap/gap |
| media | `socialpub/media.py` | local inspection (JPEG size, MP4 faststart, ffprobe). Only module that runs a process for media |
| adapters | `socialpub/adapters/` | one class per platform behind `Adapter`: `validate`, `plan`, `build_requests`, `publish` (not implemented) |
| flow | `socialpub/flow.py` | request-flow runner: placeholder substitution, polling, guards. `DryRunTransport` (mock) and `LiveTransport` (stub that raises) |
| service/cli | `service.py`, `cli.py` | validation, classification, commands `platforms validate plan run approve` |
| secrets | `secrets_provider.py` | future live token source (env var or Bitwarden CLI) wrapped in `Secret`; **not imported by dry-run code** (a test enforces it) |

## Adapter interface
`validate(post, media, errs, warns)` offline limits · `plan(post)` summary · `build_requests(post)` documented calls with placeholders only (`<ACCESS_TOKEN>`, `<IG_USER_ID>`…), each step carries `mock` answers, `capture`, `guard`, `poll` · `publish(post, transport)` raises `LiveModeDisabled` in v0.1.
Full flows: Instagram (quota check → container → poll until `FINISHED` → publish) and YouTube (init resumable → upload bytes). Skeletons (Facebook, TikTok, LinkedIn, X): validation only; `build_requests` raises `SkeletonAdapter`.

## Queue and approval
One post can target several platforms: `targets: [...]`, optional `options.<platform>` (YouTube `privacy`/`made_for_kids`, TikTok `privacy_level`, LinkedIn `owner`). Media must sit under the queue file's folder.
**Approval** (`approve <id>`) needs an interactive terminal and the exact word `YES`; it stores a SHA-256 over type, caption, title, AI flag, `public_url`, **targets**, **options** and the media bytes. Editing any of them voids the approval (`BLOCKED`). One approval covers all listed targets: to approve fewer platforms, edit `targets` and approve again. At live time a second `YES` prompt per publish is planned (not built).
**Policy:** max 2 posts / 24 h and ≥ 4 h gap **per platform**; AI flag mandatory (`false` needs `ai_false_reason`); platforms without an API AI field require "AI-generated"/"#AI" in the caption; dry-run is the default and the only mode; YouTube defaults to `private`; TikTok unaudited clients are limited to `SELF_ONLY`; `made_for_kids` must be stated explicitly.

## Temporary public media (Instagram only; YouTube/Facebook/TikTok/X/LinkedIn accept local uploads)
Instagram Login requires a public HTTPS `video_url`/`image_url` that Meta fetches. Options, no third-party publishing service:
| Option | How | Pros | Cons |
|---|---|---|---|
| **A (recommended)** | Serve one file from a server you control under an unguessable path (reverse proxy or tunnel) for the minutes of the publish, verify the served SHA-256 equals the approved fingerprint, delete after `FINISHED` | no third party holds media long-term, no cost | needs your server reachable from the internet during the window; tunnel behaviour and limits **not verified here** |
| B | Object storage (e.g. Cloudflare R2/S3) with short-lived presigned GET URL, delete afterwards | simple, no inbound exposure | a storage vendor sees the media (not tokens); small cost; needs an account |
| C | Switch to Facebook Login for Business (resumable local upload) | no public URL | needs business portfolio; broader permissions; contradicts the minimal-scope design |
| D | GitHub release/Pages | free | permanent public copy: **rejected** |
The URL is stored in the post's `public_url` (https only, part of the fingerprint). A `MediaHost` helper is a v0.2 task; nothing is hosted in v0.1.

## Tokens
Read only at the moment of a live request, from `SOCIALPUB_<PLATFORM>_TOKEN` or `bw get password <item>`; held in `Secret` (repr `Secret(***)`); never in files, queue, logs or argv. Queue saves and logs run the secret scanner/redactor. Refresh tokens (IG 60-day, Google, TikTok) must be saved back to your secret store by the operator (open design decision).

## Deliberately absent
Comments, DMs, follows, insights, ads, MCP server, hosted service, any HTTP client. Adding a platform means adding an adapter and its tests, not widening permissions.
