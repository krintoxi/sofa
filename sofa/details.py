"""A title's file, in full, for its page: the picture, every sound and subtitle track with its language and how Sofa
knows it, the file itself, and how this device gets it (as it is, repackaged or converted). One reading of the file
(sofa.media.probe, kept), nothing a list needs: the library's list carries only the languages (sofa/languages.py).
"""

import os

from . import intros, languages, media, trickplay

VIDEO_NAMES = {"h264": "H.264", "hevc": "HEVC", "mpeg4": "XviD/DivX", "msmpeg4v3": "DivX 3", "mpeg2video": "MPEG-2",
               "mpeg1video": "MPEG-1", "vc1": "VC-1", "wmv3": "WMV", "av1": "AV1", "vp9": "VP9", "vp8": "VP8",
               "theora": "Theora", "prores": "ProRes", "mjpeg": "Motion JPEG"}
AUDIO_NAMES = {"aac": "AAC", "ac3": "Dolby Digital", "eac3": "Dolby Digital+", "truehd": "Dolby TrueHD", "dts": "DTS",
               "flac": "FLAC", "opus": "Opus", "vorbis": "Vorbis", "mp3": "MP3", "mp2": "MP2", "alac": "Apple Lossless",
               "wmav2": "WMA", "wmapro": "WMA Pro", "mlp": "MLP"}
SUB_NAMES = {"subrip": "SRT", "ass": "ASS", "ssa": "SSA", "webvtt": "WebVTT", "mov_text": "MP4 text", "text": "Text",
             "hdmv_pgs_subtitle": "PGS", "dvd_subtitle": "VobSub", "dvb_subtitle": "DVB", "xsub": "XSUB",
             "eia_608": "Closed captions"}


def quality(video):
    """ "4K", "1080p", "720p", "480p"... by the picture's width where it has one (a wide film is 1920x800: 1080p)."""
    w, h = (video or {}).get("width") or 0, (video or {}).get("height") or 0
    if not h:
        return None
    for width, height, label in ((3800, 2000, "4K"), (2500, 1400, "1440p"), (1900, 1000, "1080p"), (1260, 700, "720p")):
        if w >= width or h >= height:
            return label
    return "576p" if h >= 540 else "480p" if h >= 400 else "%dp" % h


def video_name(video):
    name, raw = media.describe_video(video), (video.get("codec") or "?").upper()
    if video.get("codec") in VIDEO_NAMES and name.startswith(raw):
        name = VIDEO_NAMES[video["codec"]] + name[len(raw):]
    return name


def layout(a):
    ch = a.get("channels") or 0
    lay = (a.get("layout") or "").split("(")[0]
    if lay in ("5.1", "7.1", "6.1", "2.1", "4.0", "5.0"):
        return lay
    return {1: "Mono", 2: "Stereo", 6: "5.1", 7: "6.1", 8: "7.1"}.get(ch) or ("%d channels" % ch if ch else "")


def audio_name(a):
    name = AUDIO_NAMES.get(a.get("codec")) or (a.get("codec") or "").upper().replace("PCM_", "PCM ")
    profile = a.get("profile") or ""
    if a.get("codec") == "dts" and profile and profile != "DTS":
        name = profile.replace("DTS-HD MA", "DTS-HD Master Audio")
    if "atmos" in profile.lower():
        name += " Atmos"
    return name


def for_item(item, caps, owner=None, admin=False):
    """Everything a title's page shows of its file (see the module's note). `owner`: the show an episode belongs to."""
    info = media.probe(item["path"], detail=True) or media.probe(item["path"])
    found = languages.of(info, item.get("names") or (), item.get("subs") or ())
    out = {"id": item["id"], "read": bool(info),
           "languages": {k: found[k] for k in ("a", "s", "named", "sub_named", "tracks", "dual")},
           "original": (owner or item).get("original"),
           "file": {"size": item.get("size"), "ext": item.get("ext"), "added": item.get("added"),
                    "duration": (info or {}).get("duration") or item.get("duration"),
                    "bit_rate": (info or {}).get("bit_rate"), "chapters": len((info or {}).get("chapters") or [])},
           "has": {"intro": any(m.get("kind") == "intro" for m in intros.for_player(item["id"])),
                   "scrub": bool(trickplay.meta(item))}}
    try:
        out["file"]["modified"] = int(os.stat(item["path"]).st_mtime)
    except OSError:
        pass
    if admin:
        out["file"]["name"] = os.path.basename(item["path"])
    if not info:
        return out
    v = info.get("video")
    if v:
        out["video"] = {"quality": quality(v), "width": v.get("width"), "height": v.get("height"), "codec": video_name(v),
                        "hdr": v.get("hdr"), "fps": v.get("fps"), "bit_rate": v.get("bit_rate"),
                        "interlaced": bool(v.get("interlaced"))}
    out["audio"] = [{"index": a["index"], "code": t["code"], "by": t["by"], "name": languages.name(t["code"]),
                     "title": a.get("title") or None, "codec": audio_name(a), "layout": layout(a),
                     "bit_rate": a.get("bit_rate"), "rate": a.get("rate"), "default": a is media.default_audio(info),
                     "commentary": bool(a.get("commentary")), "described": bool(a.get("described"))}
                    for a, t in zip(info.get("audio") or [], found["audio"])]
    subs = []
    for s, t in zip(info.get("subs") or [], found["subs"]):
        forced, sdh = languages.said_flags(s)
        subs.append({"code": t["code"], "by": t["by"], "name": languages.name(t["code"]), "title": s.get("title") or None,
                     "kind": "picture" if s.get("codec") in media.IMAGE_SUBS else "text",
                     "format": SUB_NAMES.get(s.get("codec")) or (s.get("codec") or "").upper(),
                     "forced": forced, "sdh": sdh})
    for s, t in zip(item.get("subs") or [], found["subs"][len(info.get("subs") or []):]):
        flags = languages.sidecar(s.get("lang") if s.get("lang") != "und" else "")[1]
        subs.append({"code": t["code"], "by": t["by"], "name": languages.name(t["code"]), "title": None, "kind": "file",
                     "format": os.path.splitext(s["path"])[1][1:].upper(), "forced": "forced" in flags, "sdh": "sdh" in flags})
    out["subs"] = subs
    plan = media.plan(item, caps)
    out["play"] = {"mode": plan["mode"], "why": plan.get("why") or [], "max_height": plan.get("max_height")}
    return out
