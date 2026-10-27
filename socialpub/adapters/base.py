"""The one interface every platform adapter implements.

validate(post, media, errs, warns)  offline checks against the platform's documented limits
plan(post)                          human summary of what would happen
build_requests(post)                the documented API calls, with placeholders only (no secrets)
publish(post, transport)            NOT IMPLEMENTED for any platform in v0.1: always LiveModeDisabled
"""
import re

from ..core import LiveModeDisabled, SkeletonAdapter

AI_CAPTION_RE = re.compile(r"(?i)\bAI[- ]generated\b|#AI\b|made with AI|\bAI[- ]assisted\b")


class Adapter:
    name = ""
    implemented = False                 # True = full request flow exists (dry-run)
    media_types = ("VIDEO",)
    ai_flag = "api"                     # "api": platform field exists | "caption": disclose in caption text
    ai_field = ""                       # documented field name when ai_flag == "api"
    scopes = ()                         # minimum OAuth scopes (documented)
    notes = ()

    def validate(self, post, media, errs, warns):
        raise NotImplementedError

    def plan(self, post):
        return {"platform": self.name, "type": post["type"], "implemented": self.implemented,
                "ai": self.ai_field if self.ai_flag == "api" else "caption text",
                "scopes": list(self.scopes)}

    def build_requests(self, post):
        raise SkeletonAdapter(f"{self.name}: request flow not implemented yet (validation only)")

    def publish(self, post, transport=None):
        raise LiveModeDisabled("live publishing is not implemented in v0.1. See README, section 'Going live'")

    # shared helpers
    def check_ai_disclosure(self, post, errs):
        """Platforms without an API field must carry the disclosure in the caption itself."""
        if self.ai_flag == "caption" and post.get("is_ai_generated") is True:
            if not AI_CAPTION_RE.search(post.get("caption", "")):
                errs.append("AI content: this platform has no API flag, caption must say e.g. 'AI-generated' or '#AI'")

    def check_types(self, post, errs):
        if post["type"] not in self.media_types:
            errs.append(f"media type {post['type']} not supported (supports {self.media_types})")
            return False
        return True
