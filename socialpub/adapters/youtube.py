"""YouTube Shorts via YouTube Data API v3 videos.insert (resumable upload, local file: no public URL needed).
Read 2026-10-24 (developers.google.com): videos.insert scopes, status.containsSyntheticMedia, privacyStatus default
public when omitted, 10,000 units/day default quota, videos.insert 1 unit in its own 100/day bucket.
NOT verified in fetched pages: title/description limits, Shorts duration rule, private-lock for unaudited projects
(see docs/PLATFORM-MATRIX.md). Safe default here: privacy 'private' unless the post explicitly opts in."""
from .base import Adapter

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
TITLE_MAX = 100              # not verified in fetched docs
DESCRIPTION_MAX_BYTES = 5000  # not verified in fetched docs
SHORTS_MAX_SECONDS = 180      # not verified in fetched docs
PRIVACY = ("private", "unlisted", "public")


class YouTubeAdapter(Adapter):
    name = "youtube"
    implemented = True
    media_types = ("VIDEO",)
    ai_flag, ai_field = "api", "status.containsSyntheticMedia"
    scopes = ("https://www.googleapis.com/auth/youtube.upload",)

    def _opts(self, post):
        o = post.get("options", {}).get("youtube", {})
        return {"title": o.get("title") or post.get("title") or post["caption"].splitlines()[0][:TITLE_MAX],
                "privacy": o.get("privacy", "private"),
                "made_for_kids": o.get("made_for_kids")}

    def validate(self, post, media, errs, warns):
        if not self.check_types(post, errs):
            return
        o = self._opts(post)
        if not o["title"].strip() or len(o["title"]) > TITLE_MAX:
            errs.append(f"title required, max {TITLE_MAX} chars")
        if len(post.get("caption", "").encode("utf-8")) > DESCRIPTION_MAX_BYTES:
            errs.append(f"description over {DESCRIPTION_MAX_BYTES} bytes")
        if o["privacy"] not in PRIVACY:
            errs.append(f"options.youtube.privacy must be one of {PRIVACY}")
        elif o["privacy"] == "public":
            warns.append("privacy=public requested; API-project audit status for public uploads is not verified")
        if not isinstance(o["made_for_kids"], bool):
            errs.append("options.youtube.made_for_kids must be set explicitly (true/false): legal declaration")
        if media is None:
            return
        if media["ext"] not in (".mp4", ".mov"):
            errs.append("video should be .mp4 or .mov")
        if media["duration"] is not None and media["duration"] > SHORTS_MAX_SECONDS:
            warns.append(f"duration {media['duration']:.0f}s > {SHORTS_MAX_SECONDS}s: will not be a Short (limit unverified)")
        if media["width"] and media["height"] and media["width"] > media["height"]:
            warns.append("not vertical: will not be treated as a Short (rule unverified)")

    def build_requests(self, post):
        o = self._opts(post)
        auth = {"Authorization": "Bearer <ACCESS_TOKEN>"}
        desc = post["caption"]
        if "#shorts" not in desc.lower():
            desc += "\n#Shorts"
        meta = {"snippet": {"title": o["title"], "description": desc, "categoryId": "22"},
                "status": {"privacyStatus": o["privacy"], "selfDeclaredMadeForKids": o["made_for_kids"],
                           "containsSyntheticMedia": post["is_ai_generated"]}}
        return [
            {"step": "1 init resumable upload", "method": "POST", "url": UPLOAD_URL,
             "headers": {**auth, "Content-Type": "application/json; charset=UTF-8",
                         "X-Upload-Content-Type": "video/*", "X-Upload-Content-Length": "<FILE_SIZE_BYTES>"},
             "body": meta, "capture": {"UPLOAD_URL": "headers.Location"},
             "mock": [{"headers": {"Location": "https://upload.invalid/mock-session"}}]},
            {"step": "2 upload bytes", "method": "PUT", "url": "<UPLOAD_URL>",
             "headers": {"Content-Type": "video/*"}, "body_file": post["media_path"],
             "capture": {"YT_VIDEO_ID": "id"}, "mock": [{"id": "MOCK_VIDEO_1"}]},
        ]
