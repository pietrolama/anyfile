from __future__ import annotations

import subprocess
from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, EngineError, Runner, compressions, pairs
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion, Presets, Quality

AUDIO = ("mp3", "wav", "flac", "ogg", "opus", "m4a", "aac")
VIDEO = ("mp4", "mkv", "webm", "mov", "avi")

Q = Quality

# Encoders the FFmpeg build must offer for each target.
ENCODERS: dict[str, tuple[str, ...]] = {
    "mp3": ("libmp3lame",), "wav": ("pcm_s16le",), "flac": ("flac",), "ogg": ("libvorbis",),
    "opus": ("libopus",), "m4a": ("aac",), "aac": ("aac",),
    "mp4": ("libx264", "aac"), "mov": ("libx264", "aac"), "mkv": ("libx264", "aac"),
    "webm": ("libvpx-vp9", "libopus"), "avi": ("mpeg4", "libmp3lame"), "gif": ("gif",),
}

# Lossless formats: a quality preset would not change the result.
LOSSLESS_AUDIO: dict[str, list[str]] = {
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
}

Preset = tuple[list[str], str]  # (arguments, description for the user)


def _audio(codec: str, flag: str, values: tuple[str, str, str], descr: tuple[str, str, str]) -> dict:
    return {q: (["-c:a", codec, flag, v], d) for q, v, d in zip(Q, values, descr)}


AUDIO_PRESETS: dict[str, dict[Quality, Preset]] = {
    "mp3": _audio("libmp3lame", "-q:a", ("0", "2", "6"),
                  ("VBR ~245 kbit/s", "VBR ~190 kbit/s", "VBR ~115 kbit/s")),
    "ogg": _audio("libvorbis", "-q:a", ("8", "5", "2"),
                  ("~256 kbit/s", "~160 kbit/s", "~96 kbit/s")),
    "opus": _audio("libopus", "-b:a", ("192k", "128k", "64k"),
                   ("192 kbit/s", "128 kbit/s", "64 kbit/s")),
    "m4a": _audio("aac", "-b:a", ("256k", "192k", "96k"), ("256 kbit/s", "192 kbit/s", "96 kbit/s")),
    "aac": _audio("aac", "-b:a", ("256k", "192k", "96k"), ("256 kbit/s", "192 kbit/s", "96 kbit/s")),
}


def _scale(max_height: int | None) -> list[str]:
    # H.264 and VP9 in yuv420p need even dimensions.
    if max_height is None:
        return ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p"]
    return ["-vf", f"scale=-2:'trunc(min({max_height},ih)/2)*2'", "-pix_fmt", "yuv420p"]


def _h264(crf: int, speed: str, audio: str, max_height: int | None = None) -> list[str]:
    return ["-c:v", "libx264", "-preset", speed, "-crf", str(crf), *_scale(max_height),
            "-c:a", "aac", "-b:a", audio]


def _vp9(crf: int, audio: str, max_height: int | None = None) -> list[str]:
    return ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-row-mt", "1",
            "-deadline", "good", "-cpu-used", "4", *_scale(max_height),
            "-c:a", "libopus", "-b:a", audio]


def _gif(fps: int, width: int, colors: int) -> list[str]:
    vf = (f"fps={fps},scale='min({width},iw)':-1:flags=lanczos,"
          f"split[a][b];[a]palettegen=max_colors={colors}[p];[b][p]paletteuse")
    return ["-vf", vf, "-loop", "0", "-an"]


_H264_PRESETS: dict[Quality, Preset] = {
    Q.MAX: (_h264(18, "slow", "192k"), N_("H.264 CRF 18, slower encoding")),
    Q.BALANCED: (_h264(23, "medium", "160k"), "H.264 CRF 23"),
    Q.SMALL: (_h264(28, "medium", "96k", 720), N_("H.264 CRF 28, at most 720p")),
}

VIDEO_PRESETS: dict[str, dict[Quality, Preset]] = {
    "mp4": {q: ([*args, "-movflags", "+faststart"], d) for q, (args, d) in _H264_PRESETS.items()},
    "mov": _H264_PRESETS,
    "mkv": _H264_PRESETS,
    "webm": {
        Q.MAX: (_vp9(24, "160k"), "VP9 CRF 24"),
        Q.BALANCED: (_vp9(32, "128k"), "VP9 CRF 32"),
        Q.SMALL: (_vp9(40, "80k", 720), N_("VP9 CRF 40, at most 720p")),
    },
    "avi": {
        Q.MAX: ([*_scale(None), "-c:v", "mpeg4", "-q:v", "2", "-c:a", "libmp3lame", "-q:a", "2"],
                "MPEG-4 q2"),
        Q.BALANCED: ([*_scale(None), "-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3"],
                     "MPEG-4 q3"),
        Q.SMALL: ([*_scale(720), "-c:v", "mpeg4", "-q:v", "6", "-c:a", "libmp3lame", "-q:a", "5"],
                  N_("MPEG-4 q6, at most 720p")),
    },
    "gif": {
        Q.MAX: (_gif(15, 960, 256), N_("15 frames/s, up to 960 px wide")),
        Q.BALANCED: (_gif(12, 640, 256), N_("12 frames/s, up to 640 px wide")),
        Q.SMALL: (_gif(8, 400, 64), N_("8 frames/s, 400 px, 64 colours")),
    },
}

LOSSY = {"mp3", "ogg", "opus", "m4a", "aac", "mp4", "mkv", "webm", "mov", "avi"}


def _notes(source: str, target: str) -> str:
    if source in VIDEO and target in AUDIO:
        return N_("Extracts only the audio track")
    if target == "gif":
        return N_("Animation without audio: suited to short clips")
    if target in LOSSY:
        return N_("Lossy compression")
    return ""


class FFmpegEngine(Engine):
    name = "ffmpeg"
    label = "FFmpeg"
    package = "ffmpeg"
    requires = (("ffmpeg",), ("ffprobe",))

    def declared(self) -> list[Conversion]:
        return [
            *pairs(self.name, AUDIO, AUDIO, _notes),
            *pairs(self.name, VIDEO, [*VIDEO, "gif"], _notes),
            *pairs(self.name, VIDEO, AUDIO, _notes),
            *pairs(self.name, ["gif"], ["mp4", "webm"], _notes),
            *compressions(self.name, [*AUDIO_PRESETS, *(v for v in VIDEO_PRESETS if v != "gif")]),
        ]

    def probe(self) -> list[Conversion]:
        try:
            out = subprocess.run(
                [self.binary(), "-hide_banner", "-encoders"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        encoders = {line.split()[1] for line in out.splitlines()
                    if len(line.split()) > 1 and line.startswith(" ") and "=" not in line}
        return [c for c in self.declared() if set(ENCODERS[c.target]) <= encoders]

    def presets(self, target: str) -> Presets:
        table = AUDIO_PRESETS.get(target) or VIDEO_PRESETS.get(target) or {}
        return {q: _(descr) for q, (_args, descr) in table.items()}

    def _duration(self, src: Path, runner: Runner) -> float | None:
        try:
            out = runner.run([
                self.binary(1), "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", src,
            ])
            value = float(out.strip().splitlines()[0])
        except (EngineError, ValueError, IndexError):
            return None
        return value if value > 0 else None

    def _has_audio(self, src: Path, runner: Runner) -> bool:
        try:
            out = runner.run([self.binary(1), "-v", "error", "-select_streams", "a",
                              "-show_entries", "stream=index", "-of", "csv=p=0", src])
        except EngineError:
            return True  # when in doubt FFmpeg decides, with its own message
        return bool(out.strip())

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        target, quality = conversion.target, ctx.quality
        if target in AUDIO and not self._has_audio(src, ctx.runner):
            raise EngineError(_("“{name}” has no audio track to extract").format(name=ctx.original.name))
        if target in LOSSLESS_AUDIO:
            codec_args = ["-vn", *LOSSLESS_AUDIO[target]]
        elif target in AUDIO_PRESETS:
            codec_args = ["-vn", *AUDIO_PRESETS[target][quality][0]]
        else:
            codec_args = VIDEO_PRESETS[target][quality][0]

        duration = self._duration(src, ctx.runner)
        ctx.progress(0.0 if duration else None)

        def on_line(line: str) -> None:
            if duration and line.startswith("out_time_us="):
                value = line.partition("=")[2]
                if value.isdigit():
                    ctx.progress(min(int(value) / 1_000_000 / duration, 1.0))

        ctx.runner.run(
            [self.binary(), "-hide_banner", "-nostdin", "-y", "-i", src, *codec_args,
             "-progress", "pipe:1", "-nostats", dst],
            on_line=on_line, tool="FFmpeg",
        )
