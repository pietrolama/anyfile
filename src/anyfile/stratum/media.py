"""Anatomy of audio-video containers: the tracks FFmpeg finds, taken out without re-encoding."""

from __future__ import annotations

import json
import re
from pathlib import Path

from anyfile.core import formats
from anyfile.engines.base import ConversionContext, EngineError, Runner
from anyfile.engines.ffmpeg import AUDIO_PRESETS, LOSSLESS_AUDIO, FFmpegEngine, input_args
from anyfile.i18n import _, format_number, ngettext
from anyfile.models.component import Anatomy, Component, Kind
from anyfile.models.conversion import Quality

SOURCES = ("mkv", "webm", "mp4", "mov", "avi", "mp3", "flac", "m4a", "ogg", "opus")

CODECS = {
    "h264": "H.264", "hevc": "H.265", "av1": "AV1", "vp9": "VP9", "vp8": "VP8", "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2", "aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis",
    "flac": "FLAC", "alac": "ALAC", "ac3": "AC-3", "eac3": "E-AC-3", "dts": "DTS", "truehd": "TrueHD",
    "subrip": "SubRip", "ass": "ASS", "ssa": "SSA", "webvtt": "WebVTT", "mov_text": "MP4 Timed Text",
    "hdmv_pgs_subtitle": "PGS", "dvd_subtitle": "VobSub", "dvb_subtitle": "DVB", "mjpeg": "JPEG",
    "png": "PNG",
}

# Container of an extracted track, chosen by codec so the packets are copied as they are.
AUDIO_EXT = {"aac": "m4a", "alac": "m4a", "mp3": "mp3", "opus": "opus", "vorbis": "ogg",
             "flac": "flac", "ac3": "ac3", "eac3": "eac3", "dts": "dts"}
# Text subtitles keep their format; images (PGS) go to their raw format, the others to
# Matroska, which carries every kind of subtitle.
SUBTITLE_EXT = {"subrip": "srt", "ass": "ass", "ssa": "ass", "webvtt": "vtt", "mov_text": "srt",
                "hdmv_pgs_subtitle": "sup"}
COVER_EXT = {"mjpeg": "jpg", "png": "png"}
# Formats a track can be converted to while it is extracted, in the order offered.
AUDIO_TARGETS = ("mp3", "m4a", "opus", "ogg", "flac", "wav")
SUBTITLE_TARGETS = {"srt": "srt", "ass": "ass", "vtt": "webvtt"}  # extension → encoder
# Channel layouts libopus encodes; any other is mapped to the nearest one.
OPUS_LAYOUTS = ("7.1", "6.1", "5.1", "5.0", "quad", "3.0", "stereo", "mono")
# Subtitles made of text: only these can change format (PGS and DVD ones are images).
TEXT_SUBTITLES = {"subrip", "ass", "ssa", "webvtt", "mov_text"}
# Video codecs an MP4 or WebM can hold; any other video goes to Matroska.
MP4_VIDEO = {"h264", "hevc", "av1", "mpeg4"}
WEBM_VIDEO = {"vp8", "vp9", "av1"}

# Muxer for each extension: named explicitly, never guessed from the file name.
MUXERS = {
    "m4a": "ipod", "mp3": "mp3", "opus": "opus", "ogg": "ogg", "flac": "flac", "ac3": "ac3",
    "eac3": "eac3", "dts": "dts", "wav": "wav", "mka": "matroska", "srt": "srt", "ass": "ass",
    "vtt": "webvtt", "sup": "sup", "mks": "matroska", "mkv": "matroska", "mp4": "mp4",
    "webm": "webm", "jpg": "image2", "png": "image2",
}
# Demuxer to read the result back: some formats are written and read by different names.
READERS = {**MUXERS, "m4a": "mov", "mp4": "mov", "opus": "ogg", "mka": "matroska", "mks": "matroska",
           "webm": "matroska"}

_LANGUAGE = re.compile(r"[a-z]{2,3}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
TITLE_MAX = 80


def probe(ffprobe: str, src: Path, source: str, runner: Runner) -> dict:
    out = runner.run([ffprobe, "-v", "error", *input_args(source), "-of", "json",
                      "-show_streams", "-show_format", src], tool="FFprobe")
    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError as e:
        raise EngineError(_("FFprobe gave an unreadable answer"), details=str(e)) from e
    return data if isinstance(data, dict) else {}


def anatomy(data: dict, source: str) -> Anatomy:
    """The components described by FFprobe's JSON. Streams that are not tracks (data,
    attachments, timecodes) are left out: they are not something to take out."""
    components = []
    for stream in data.get("streams") or []:
        if isinstance(stream, dict) and (c := _component(stream, source)):
            components.append(c)
    summary = formats.get(source).label
    duration = _float((data.get("format") or {}).get("duration"))
    if duration:
        summary += f" · {_clock(duration)}"
    return Anatomy(tuple(components), summary, duration)


def _component(stream: dict, source: str) -> Component | None:
    index, kind = stream.get("index"), stream.get("codec_type")
    if not isinstance(index, int):
        return None
    codec = str(stream.get("codec_name") or "")
    tags = {str(k).lower(): str(v) for k, v in (stream.get("tags") or {}).items()}
    disposition = stream.get("disposition") or {}
    language = tags.get("language", "").lower()
    common = dict(
        id=str(index), codec=CODECS.get(codec, codec.upper() or "?"),
        language=language if _LANGUAGE.fullmatch(language) and language != "und" else "",
        title=_CONTROL.sub(" ", tags.get("title", "")).strip()[:TITLE_MAX],
        default=bool(disposition.get("default")), forced=bool(disposition.get("forced")),
        metadata={"codec_name": codec, "channels": str(stream.get("channels") or "")},
    )
    if kind == "video" and disposition.get("attached_pic"):
        ext = COVER_EXT.get(codec, "")
        return Component(kind=Kind.COVER, ext=ext, details=_size(stream), extractable=bool(ext),
                         reason="" if ext else _("this image format cannot be saved as it is"),
                         **common)
    if kind == "video":
        return Component(kind=Kind.VIDEO, ext=_video_ext(codec, source), details=_video_details(stream),
                         **common)
    if kind == "audio":
        return Component(kind=Kind.AUDIO, ext=_audio_ext(codec), details=_audio_details(stream), **common)
    if kind == "subtitle":
        return Component(kind=Kind.SUBTITLE, ext=SUBTITLE_EXT.get(codec, "mks"), **common)
    return None


def _video_ext(codec: str, source: str) -> str:
    if source in ("mp4", "mov") and codec in MP4_VIDEO:
        return "mp4"
    if source == "webm" and codec in WEBM_VIDEO:
        return "webm"
    return "mkv"


def _audio_ext(codec: str) -> str:
    if codec in AUDIO_EXT:
        return AUDIO_EXT[codec]
    # WAV holds little-endian PCM; anything else goes to Matroska audio.
    return "wav" if codec.startswith("pcm_") and codec.endswith("le") else "mka"


def _size(stream: dict) -> str:
    w, h = stream.get("width"), stream.get("height")
    return f"{w}×{h}" if isinstance(w, int) and isinstance(h, int) else ""


def _video_details(stream: dict) -> str:
    parts = [_size(stream)]
    num, _sep, den = str(stream.get("avg_frame_rate") or "").partition("/")
    if num.isdigit() and den.isdigit() and int(den) and int(num):
        parts.append(_("{fps} fps").format(fps=_number(int(num) / int(den), 3)))
    return " · ".join(p for p in parts if p)


def _audio_details(stream: dict) -> str:
    parts = []
    channels = stream.get("channels")
    layout = str(stream.get("channel_layout") or "")
    if layout.startswith(("5.1", "7.1")):
        parts.append(layout.split("(")[0])
    elif isinstance(channels, int) and channels > 0:
        parts.append(ngettext("{n} channel", "{n} channels", channels).format(n=channels))
    rate = str(stream.get("sample_rate") or "")
    if rate.isdigit():
        parts.append(_("{rate} kHz").format(rate=_number(int(rate) / 1000, 1)))
    return " · ".join(parts)


def _number(value: float, decimals: int) -> str:
    """25 rather than 25.000, 23.976 as it is."""
    return format_number(value, decimals).rstrip("0").rstrip(".,")


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def targets(component: Component, available: set[str]) -> list[str]:
    """Extensions the component can be saved as: first its own, copied as it is, then
    the formats it can be converted to (`available`: audio formats FFmpeg can encode)."""
    if not component.extractable:
        return []
    if component.kind is Kind.AUDIO:
        converted = [t for t in AUDIO_TARGETS if t in available]
    elif component.kind is Kind.SUBTITLE and component.metadata.get("codec_name") in TEXT_SUBTITLES:
        converted = list(SUBTITLE_TARGETS)
    else:
        converted = []
    return [component.ext, *(t for t in converted if t != component.ext)]


def codec_args(component: Component, target: str = "", quality: Quality = Quality.BALANCED) -> list[str]:
    target = target or component.ext
    if target != component.ext and component.kind is Kind.SUBTITLE:
        return ["-c:s", SUBTITLE_TARGETS[target]]
    if target != component.ext:
        args = list(LOSSLESS_AUDIO.get(target) or AUDIO_PRESETS[target][quality][0])
        channels = component.metadata.get("channels", "")
        surround = channels.isdigit() and int(channels) > 2
        if target == "mp3" and surround:
            args += ["-ac", "2"]  # MP3 holds at most two channels: 5.1 becomes stereo
        elif target == "opus" and surround:
            # libopus knows the plain layouts only: 5.1(side), common in films, becomes 5.1.
            args += ["-af", "aformat=channel_layouts=" + "|".join(OPUS_LAYOUTS)]
        return args
    if component.metadata.get("codec_name") == "mov_text":
        # MP4 text has no file format of its own: it becomes SubRip, text and timings unchanged.
        return ["-c:s", "srt"]
    if component.kind is Kind.COVER:
        return ["-c", "copy", "-frames:v", "1", "-update", "1"]
    return ["-c", "copy"]


def extract(engine: FFmpegEngine, component: Component, src: Path, source: str, dst: Path,
            duration: float | None, ctx: ConversionContext, target: str = "") -> None:
    """Writes the component to dst: its packets copied as they are, or converted to
    `target` (an extension from targets()) at the context's quality. The timestamps
    stay those of the file (-copyts): FFmpeg would otherwise shift them by the start of
    the earliest track, and extracted subtitles would drift from the video."""
    ctx.progress(0.0 if duration else None)

    def on_line(line: str) -> None:
        if duration and line.startswith("out_time_us="):
            value = line.partition("=")[2]
            if value.isdigit():
                ctx.progress(min(int(value) / 1_000_000 / duration, 1.0))

    ctx.runner.run(
        [engine.binary(), "-hide_banner", "-nostdin", "-y", *input_args(source), "-copyts", "-i", src,
         "-map", f"0:{component.id}", "-map_metadata", "-1", "-map_chapters", "-1",
         *codec_args(component, target, ctx.quality), "-f", MUXERS[target or component.ext],
         "-progress", "pipe:1", "-nostats", dst],
        on_line=on_line, tool="FFmpeg",
    )


def check(engine: FFmpegEngine, component: Component, path: Path, runner: Runner,
          target: str = "") -> str | None:
    """Why the extracted file is not right, or None. The exit code of FFmpeg is not
    enough: the file must contain exactly one track, of the kind that was asked for."""
    if not path.is_file() or path.stat().st_size == 0:
        return _("The produced file is empty")
    try:
        out = runner.run([engine.binary(1), "-v", "error", "-protocol_whitelist", "file",
                          "-f", READERS[target or component.ext], "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", path], tool="FFprobe")
    except EngineError:
        return _("The produced file cannot be read back")
    expected = "audio" if component.kind is Kind.AUDIO else (
        "subtitle" if component.kind is Kind.SUBTITLE else "video")
    found = [line.strip(", ") for line in out.splitlines() if line.strip()]
    if found != [expected]:
        return _("The produced file does not contain the expected track")
    return None
