"""Local media inspection (no network). ffprobe is the only subprocess used for media."""
import json
import os
import shutil
import subprocess
from pathlib import Path


class MediaError(ValueError):
    pass


def jpeg_size(path):
    data = Path(path).read_bytes()
    if data[:2] != b"\xff\xd8":
        raise MediaError("not a JPEG file")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h
        i += 2 + length
    raise MediaError("JPEG dimensions not found")


def moov_before_mdat(path):
    """True if moov precedes mdat (faststart), False if not, None if the box layout is unreadable."""
    size = os.path.getsize(path)
    pos = 0
    with open(path, "rb") as f:
        while pos + 8 <= size:
            f.seek(pos)
            hdr = f.read(16)
            box = int.from_bytes(hdr[:4], "big")
            typ = hdr[4:8]
            if box == 1:
                box = int.from_bytes(hdr[8:16], "big")
            elif box == 0:
                box = size - pos
            if typ == b"moov":
                return True
            if typ == b"mdat":
                return False
            if box < 8:
                return None
            pos += box
    return None


def _fps(stream):
    for key in ("avg_frame_rate", "r_frame_rate"):
        v = stream.get(key, "0/0")
        try:
            a, b = v.split("/")
            if float(b) != 0 and float(a) != 0:
                return float(a) / float(b)
        except ValueError:
            pass
    return 0.0


def _ffprobe(path):
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise MediaError("ffprobe could not read the file: " + out.stderr.strip()[:200])
    return json.loads(out.stdout)


def inspect(path, kind):
    """Normalised facts about a media file. Returns None if ffprobe is missing for a video.
    Keys (video): kind,size,ext,faststart,vcodec,pix_fmt,field_order,width,height,fps,duration,bitrate,
    has_audio,acodec,sample_rate,channels. (image): kind,size,ext,width,height."""
    p = Path(path)
    base = {"kind": kind, "size": p.stat().st_size, "ext": p.suffix.lower()}
    if kind == "IMAGE":
        if base["ext"] in (".jpg", ".jpeg"):
            base["width"], base["height"] = jpeg_size(p)
        return base
    info = _ffprobe(p)
    if info is None:
        return None
    v = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    a = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not v:
        raise MediaError("no video stream")
    v0 = v[0]
    fmt = info.get("format", {})
    base.update({
        "faststart": moov_before_mdat(p),
        "vcodec": v0.get("codec_name"), "pix_fmt": v0.get("pix_fmt"),
        "field_order": v0.get("field_order", "progressive"),
        "width": int(v0.get("width", 0)), "height": int(v0.get("height", 0)),
        "fps": _fps(v0),
        "duration": float(fmt["duration"]) if "duration" in fmt else None,
        "bitrate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        "has_audio": bool(a),
    })
    if a:
        base.update({"acodec": a[0].get("codec_name"), "sample_rate": int(a[0].get("sample_rate", 0)),
                     "channels": int(a[0].get("channels", 0))})
    return base
