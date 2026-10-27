"""Token source for FUTURE live mode. Dry-run never imports or calls this.

Tokens come only from an environment variable or the Bitwarden CLI at run time. They are returned
wrapped in `Secret`, whose str()/repr() never reveals the value, and are never written anywhere.
Nothing in the project stores, logs or serialises a token.
"""
import os
import shutil
import subprocess

ENV_NAMES = {
    "instagram": "SOCIALPUB_INSTAGRAM_TOKEN",
    "youtube": "SOCIALPUB_YOUTUBE_TOKEN",
    "facebook": "SOCIALPUB_FACEBOOK_TOKEN",
    "tiktok": "SOCIALPUB_TIKTOK_TOKEN",
    "linkedin": "SOCIALPUB_LINKEDIN_TOKEN",
    "x": "SOCIALPUB_X_TOKEN",
}


class Secret:
    __slots__ = ("_v",)

    def __init__(self, value):
        self._v = value

    def reveal(self):
        """Only the (future) live transport may call this, at the moment of the request."""
        return self._v

    def __repr__(self):
        return "Secret(***)"

    __str__ = __repr__


def get_token(platform, bw_item=None):
    """Env var first, then `bw get password <bw_item>` (Bitwarden CLI, session already unlocked by the operator)."""
    name = ENV_NAMES[platform]
    value = os.environ.get(name)
    if value:
        return Secret(value)
    if bw_item:
        exe = shutil.which("bw")
        if not exe:
            raise RuntimeError("Bitwarden CLI (bw) not found and " + name + " is not set")
        out = subprocess.run([exe, "get", "password", bw_item], capture_output=True, text=True, timeout=30)
        if out.returncode != 0 or not out.stdout.strip():
            raise RuntimeError("bw could not return the item (is the vault unlocked?)")
        return Secret(out.stdout.strip())
    raise RuntimeError(name + " is not set")
