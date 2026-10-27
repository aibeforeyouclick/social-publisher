"""Skeleton adapters: offline validation against documented limits + documented endpoints. No request flow yet
(build_requests raises SkeletonAdapter). Sources and what was/was not verified: docs/PLATFORM-MATRIX.md."""
from .base import Adapter


class FacebookAdapter(Adapter):
    """Facebook Page Reels (Meta docs read 2026-10-24): POST /{page-id}/video_reels upload_phase start ->
    rupload.facebook.com upload -> upload_phase=finish (video_state DRAFT|SCHEDULED|PUBLISHED)."""
    name = "facebook"
    ai_flag, ai_field = "api", "is_ai_generated"
    scopes = ("pages_show_list", "pages_read_engagement", "pages_manage_posts")

    def validate(self, post, media, errs, warns):
        if not self.check_types(post, errs) or media is None:
            return
        if media["duration"] is not None and not (3 <= media["duration"] <= 90):
            errs.append("Page Reels: duration must be 3-90 s")
        if media["fps"] and not (24 <= media["fps"] <= 60):
            errs.append("Page Reels: 24-60 fps")
        if media["width"] < 540 or media["height"] < 960:
            errs.append("Page Reels: minimum 540x960")
        if media["height"] and abs(media["width"] / media["height"] - 9 / 16) > 0.02:
            errs.append("Page Reels: 9:16 required")
        if media.get("has_audio") and media["acodec"] != "aac":
            errs.append("audio must be AAC-LC")
        warns.append("scheduling (10 min - 29 days ahead) and 30 posts/24h are platform limits; ours are stricter")


class TikTokAdapter(Adapter):
    """TikTok Content Posting API, Direct Post (docs read 2026-10-24). Unaudited clients: SELF_ONLY (private),
    max 5 users / 24h. Public posting needs a TikTok audit. Privacy must be chosen explicitly (no default)."""
    name = "tiktok"
    ai_flag, ai_field = "caption", ""   # API AI-label field NOT verified in fetched docs -> disclose in caption too
    scopes = ("video.publish",)

    def validate(self, post, media, errs, warns):
        if not self.check_types(post, errs):
            return
        o = post.get("options", {}).get("tiktok", {})
        if o.get("privacy_level") not in ("SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS",
                                          "FOLLOWER_OF_CREATOR"):
            errs.append("options.tiktok.privacy_level must be chosen explicitly (no default, per TikTok guidelines)")
        elif o["privacy_level"] != "SELF_ONLY" and not o.get("client_audited") is True:
            errs.append("TikTok: unaudited API clients can only post SELF_ONLY (private); set client_audited=true "
                        "only after TikTok's audit passed")
        if media and media["duration"] is not None and media["duration"] < 3:
            errs.append("duration under 3 s")
        warns.append("max duration comes from creator_info at live time; consent UI duties are the operator's (see docs/PLATFORM-MATRIX.md)")


class LinkedInAdapter(Adapter):
    """LinkedIn Videos API + Posts API (Microsoft Learn read 2026-10-24): 3 s-30 min, 75 KB-500 MB, MP4."""
    name = "linkedin"
    ai_flag, ai_field = "caption", ""
    scopes = ("w_member_social",)       # or w_organization_social for a Page

    def validate(self, post, media, errs, warns):
        if not self.check_types(post, errs):
            return
        owner = post.get("options", {}).get("linkedin", {}).get("owner")
        if not (isinstance(owner, str) and owner.startswith(("urn:li:person:", "urn:li:organization:"))):
            errs.append("options.linkedin.owner must be a urn:li:person:/urn:li:organization: URN")
        if media:
            if media["ext"] != ".mp4":
                errs.append("LinkedIn video must be MP4")
            if not (75 * 1024 <= media["size"] <= 500 * 1024 * 1024):
                errs.append("LinkedIn video size must be 75 KB .. 500 MB")
            if media["duration"] is not None and not (3 <= media["duration"] <= 1800):
                errs.append("LinkedIn video duration must be 3 s .. 30 min")
        warns.append("product access/approval needed for w_organization_social is NOT verified")


class XAdapter(Adapter):
    """X API v2: chunked media upload then POST /2/tweets (docs read 2026-10-24). Pay per use:
    $0.015 per post, $0.20 per post containing a URL (docs fetched; rates may change)."""
    name = "x"
    ai_flag, ai_field = "caption", ""
    scopes = ()                          # OAuth 2.0 PKCE scopes NOT verified in fetched docs
    CAPTION_MAX = 280                    # not verified in fetched docs

    def validate(self, post, media, errs, warns):
        if not self.check_types(post, errs):
            return
        cap = post.get("caption", "")
        if len(cap) > self.CAPTION_MAX:
            errs.append(f"post text {len(cap)} > {self.CAPTION_MAX} chars (limit unverified; Premium differs)")
        if "http://" in cap or "https://" in cap:
            warns.append("post with a URL costs $0.20 instead of $0.015 (pay-per-use, docs fetched 2026-10-24)")
        if media and media["duration"] is not None and media["duration"] > 20 * 60:
            errs.append("video over 20 min (standard account limit)")
        warns.append("each post costs money: needs a budget decision by the operator before any live use")
