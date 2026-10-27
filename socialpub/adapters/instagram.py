"""Instagram (Instagram API with Instagram Login). Limits from Meta's Instagram Platform
docs (Content Publishing, IG User Media; read 2026-10-24). Full dry-run flow; scopes: instagram_business_basic + instagram_business_content_publish."""
import re

from ..core import MAX_POSTS_PER_24H
from .base import Adapter

API_HOST = "https://graph.instagram.com"
API_VERSION = "v26.0"
CAPTION_MAX, HASHTAG_MAX, MENTION_MAX = 2200, 30, 20
IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGE_ASPECT = (0.8, 1.91)
IMAGE_WIDTH_WARN = (320, 1440)
REEL_MAX_BYTES = 300 * 1024 * 1024
REEL_DURATION = (3.0, 900.0)
REEL_FPS = (23.0, 60.0)
REEL_MAX_WIDTH = 1920
REEL_ASPECT = (0.01, 10.0)
REEL_MAX_BITRATE = 25_000_000 + 128_000
STATUS_POLL_SECONDS, STATUS_POLL_MAX = 60, 5


class InstagramAdapter(Adapter):
    name = "instagram"
    implemented = True
    media_types = ("VIDEO", "IMAGE")
    ai_flag, ai_field = "api", "is_ai_generated"
    scopes = ("instagram_business_basic", "instagram_business_content_publish")

    def validate(self, post, media, errs, warns):
        if not self.check_types(post, errs):
            return
        cap = post.get("caption", "")
        if len(cap) > CAPTION_MAX:
            errs.append(f"caption {len(cap)} chars > {CAPTION_MAX}")
        if len(re.findall(r"#\w+", cap)) > HASHTAG_MAX:
            errs.append(f"more than {HASHTAG_MAX} hashtags")
        if len(re.findall(r"@[\w.]+", cap)) > MENTION_MAX:
            errs.append(f"more than {MENTION_MAX} @mentions")
        url = post.get("public_url")
        if url is not None and not (isinstance(url, str) and url.startswith("https://")):
            errs.append("public_url must start with https://")
        if media is None:
            return
        (self._image if post["type"] == "IMAGE" else self._reel)(media, errs, warns)

    def _image(self, m, errs, warns):
        if m["ext"] not in (".jpg", ".jpeg"):
            errs.append("IMAGE must be JPEG (.jpg/.jpeg) - the only format Meta accepts")
            return
        if m["size"] > IMAGE_MAX_BYTES:
            errs.append("image larger than 8 MB")
        w, h = m["width"], m["height"]
        if not (IMAGE_ASPECT[0] - 0.001 <= w / h <= IMAGE_ASPECT[1] + 0.001):
            errs.append(f"image aspect ratio {w}:{h} outside 4:5 .. 1.91:1")
        if not (IMAGE_WIDTH_WARN[0] <= w <= IMAGE_WIDTH_WARN[1]):
            warns.append(f"image width {w}px will be rescaled by Meta (320-1440)")
        warns.append("MPO/JPS variants and sRGB colour space are not verified")

    def _reel(self, m, errs, warns):
        if m["ext"] not in (".mp4", ".mov"):
            errs.append("REELS must be .mp4 or .mov")
            return
        if m["size"] > REEL_MAX_BYTES:
            errs.append("reel larger than 300 MB")
        if m["faststart"] is False:
            errs.append("moov atom is not at the front of the file (re-mux with -movflags +faststart)")
        elif m["faststart"] is None:
            warns.append("could not read MP4 box layout (moov position not verified)")
        if m["vcodec"] not in ("h264", "hevc"):
            errs.append(f"video codec {m['vcodec']} (need H.264 or HEVC)")
        if m["pix_fmt"] not in ("yuv420p", "yuvj420p"):
            errs.append(f"pixel format {m['pix_fmt']} (need 4:2:0)")
        if m["field_order"] not in ("progressive", "unknown"):
            errs.append("video is interlaced (need progressive)")
        w, h = m["width"], m["height"]
        if w > REEL_MAX_WIDTH:
            errs.append(f"width {w} > {REEL_MAX_WIDTH}")
        if h and not (REEL_ASPECT[0] <= w / h <= REEL_ASPECT[1]):
            errs.append("aspect ratio outside 0.01:1 .. 10:1")
        elif h and abs(w / h - 9 / 16) > 0.02:
            warns.append(f"aspect ratio {w}:{h} is not 9:16 (Meta recommends 9:16 to avoid cropping)")
        if not (REEL_FPS[0] - 0.05 <= m["fps"] <= REEL_FPS[1] + 0.05):
            errs.append(f"frame rate {m['fps']:.2f} outside 23-60 FPS")
        if m["duration"] is None:
            errs.append("duration unknown")
        elif not (REEL_DURATION[0] <= m["duration"] <= REEL_DURATION[1]):
            errs.append(f"duration {m['duration']:.1f}s outside 3 s .. 15 min")
        if m["bitrate"] and m["bitrate"] > REEL_MAX_BITRATE:
            errs.append("bitrate above 25 Mbps video + 128 kbps audio")
        if m["has_audio"]:
            if m["acodec"] != "aac":
                errs.append(f"audio codec {m['acodec']} (need AAC)")
            if m["sample_rate"] > 48000:
                errs.append("audio sample rate above 48 kHz")
            if m["channels"] not in (1, 2):
                errs.append("audio must be mono or stereo")
        else:
            warns.append("reel has no audio track")
        warns.append("edit lists and closed GOP are not verified")

    def build_requests(self, post):
        """Documented Graph calls in order. Placeholders only; the token is never part of a request dict."""
        base = f"{API_HOST}/{API_VERSION}"
        ig = "<IG_USER_ID>"
        auth = {"Authorization": "Bearer <ACCESS_TOKEN>"}
        media_url = post.get("public_url") or "<PUBLIC_URL_REQUIRED_AT_LIVE>"
        body = {"caption": post["caption"], "is_ai_generated": post["is_ai_generated"]}
        if post["type"] == "VIDEO":
            body.update({"media_type": "REELS", "video_url": media_url})
        else:
            body.update({"image_url": media_url})
        reqs = [
            {"step": "0 quota check", "method": "GET",
             "url": f"{base}/{ig}/content_publishing_limit?fields=quota_usage,config", "headers": auth,
             "guard": {"path": "data.0.quota_usage", "max_exclusive": MAX_POSTS_PER_24H},
             "mock": [{"data": [{"quota_usage": 0, "config": {"quota_total": 100, "quota_duration": 86400}}]}]},
            {"step": "1 create container", "method": "POST", "url": f"{base}/{ig}/media",
             "headers": {**auth, "Content-Type": "application/json"}, "body": body,
             "capture": {"IG_CONTAINER_ID": "id"}, "mock": [{"id": "MOCK_CONTAINER_1"}]},
        ]
        if post["type"] == "VIDEO":
            reqs.append({"step": "2 status poll", "method": "GET",
                         "url": f"{base}/<IG_CONTAINER_ID>?fields=status_code", "headers": auth,
                         "poll": {"until": {"status_code": "FINISHED"}, "fail_on": ["ERROR", "EXPIRED"],
                                  "max": STATUS_POLL_MAX, "interval_seconds": STATUS_POLL_SECONDS},
                         "mock": [{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}]})
        reqs.append({"step": "3 publish", "method": "POST", "url": f"{base}/{ig}/media_publish",
                     "headers": {**auth, "Content-Type": "application/json"},
                     "body": {"creation_id": "<IG_CONTAINER_ID>"}, "mock": [{"id": "MOCK_MEDIA_1"}]})
        return reqs
