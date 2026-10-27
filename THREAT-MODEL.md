# THREAT-MODEL – social-publisher v0.1 (hosted publishers vs self-hosted)

Scope: a tool that will one day publish from accounts you own. v0.1 is dry-run: no HTTP code, no tokens. This page is a design analysis, not an audit; it compares two *architectures*, not any named product.

## Assets
Account tokens (Instagram/Google/TikTok/…); app secrets; the content queue; the approval record; media.

## Hosted publisher vs this tool (architecture comparison)
| Topic | Typical hosted multi-platform publisher | social-publisher |
|---|---|---|
| **Token custody** | The service stores your access tokens for every connected account | Tokens stay on your machine/vault. Read at request time from an env var or Bitwarden CLI, wrapped in `Secret`, never written to file/log/queue |
| **Breach blast radius** | A service-side breach exposes the tokens of all its customers | No vendor. A compromise of your own computer is the risk (below) |
| **Scopes** | Often account-wide (delete posts, messages, disconnect accounts, paid campaigns), narrower scopes may be optional | Only the publish scopes per platform (`scopes` in each adapter); no comments/DM/follow/ads/insights code exists, a test asserts forbidden endpoints are absent |
| **Agent/MCP surface** | A hosted MCP/agent endpoint can act on all connected accounts | No MCP, no server, no daemon. The CLI acts only on approved queue items |
| **Availability** | Depends on the operator and its terms | Depends on you and the platforms |
| **Approval** | Varies | Approval bound to SHA-256 of caption, title, AI flag, targets, options, `public_url`, media bytes; TTY + exact `YES`; any edit voids it |
| **Maintenance** | The operator tracks API changes | You |

## Threats to this tool and what v0.1 does
| # | Threat | Mitigation in v0.1 | Gap / later |
|---|---|---|---|
| 1 | Token leaks to git/log/queue | Secret patterns (Meta, Google, TikTok, generic) scanned on queue load and before every save; log redacted; `.gitignore` for `.env`, logs, local queues; tests prove an env token never appears in stdout/log/queue | Patterns are heuristic: also run a scanner such as gitleaks before pushing |
| 2 | Token printed via repr/exception | `Secret.__repr__/__str__` = `Secret(***)` | a live transport must never put the header in an exception message |
| 3 | Unapproved or altered content published | Fingerprint approval + status gate + TTY `YES` | second `YES` at publish time not built yet |
| 4 | Malicious queue entry reads arbitrary file (e.g. `~/.ssh`) | `media_path` must resolve inside the queue file's folder (tests incl. `../` and absolute paths) | symlinks inside the folder resolve before the check |
| 5 | Approved post redirected to other media via `public_url` | `public_url` is part of the fingerprint; must be https | live mode must also hash the served bytes |
| 6 | Accidental live publishing | No HTTP client anywhere (AST test bans network modules), `LiveTransport` only raises, sockets blocked at runtime in dry-run, `run --live` exits 3 | when live arrives: explicit flag + env gate + budget cap |
| 7 | Spam / platform sanctions | per-platform cap 2/24 h, ≥4 h gap, quota guard step, no engagement features (users can change the constants: see README) | – |
| 8 | Unlabelled AI content | `is_ai_generated` mandatory; platform field where it exists, caption disclosure otherwise (enforced) | TikTok API field unverified |
| 9 | Command/code injection | no `eval/exec/shell=True/pickle` (test); only `ffprobe` and `bw` are spawned, with argument lists | `ffprobe` parses untrusted media: keep it updated |
| 10 | Dependency compromise | zero third-party dependencies | keep it that way; if one is added, pin + hash |
| 11 | Stolen refresh tokens from the operator's machine | not stored by the tool | vault and OS account hygiene are the operator's |
| 12 | Wrong account (token for another profile) | – | live mode must verify the account id (e.g. `GET /me`) before publishing |
| 13 | Public hosting of media during an Instagram publish | see `docs/ARCHITECTURE.md`: unguessable path, short life, hash check | not built |

## Residual risks the operator owns
Platform terms on automated posting (see README "Terms & responsible use"), TikTok audit requirements, API behaviour differing from the docs, secret-store and computer security, account creation.
