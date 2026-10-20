from __future__ import annotations

import subprocess
from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, EngineError, Runner, pairs
from anyfile.models.conversion import Conversion

AUDIO = ("mp3", "wav", "flac", "ogg", "opus", "m4a", "aac")
VIDEO = ("mp4", "mkv", "webm", "mov", "avi")

# formato → (encoder richiesti, argomenti di codifica)
AUDIO_CODECS: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "mp3": (("libmp3lame",), ["-c:a", "libmp3lame", "-q:a", "2"]),
    "wav": (("pcm_s16le",), ["-c:a", "pcm_s16le"]),
    "flac": (("flac",), ["-c:a", "flac"]),
    "ogg": (("libvorbis",), ["-c:a", "libvorbis", "-q:a", "5"]),
    "opus": (("libopus",), ["-c:a", "libopus", "-b:a", "128k"]),
    "m4a": (("aac",), ["-c:a", "aac", "-b:a", "192k"]),
    "aac": (("aac",), ["-c:a", "aac", "-b:a", "192k"]),
}

# H.264 e VP9 in yuv420p richiedono dimensioni pari.
_EVEN = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p"]
_H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "23", *_EVEN]
_GIF_FILTER = (
    "fps=12,scale='min(640,iw)':-1:flags=lanczos,"
    "split[a][b];[a]palettegen[p];[b][p]paletteuse"
)

VIDEO_CODECS: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "mp4": (("libx264", "aac"), [*_H264, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]),
    "mov": (("libx264", "aac"), [*_H264, "-c:a", "aac", "-b:a", "160k"]),
    "mkv": (("libx264", "aac"), [*_H264, "-c:a", "aac", "-b:a", "160k"]),
    "webm": (("libvpx-vp9", "libopus"), [
        "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1",
        "-deadline", "good", "-cpu-used", "4", *_EVEN, "-c:a", "libopus", "-b:a", "128k",
    ]),
    "avi": (("mpeg4", "libmp3lame"), ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3"]),
    "gif": (("gif",), ["-vf", _GIF_FILTER, "-loop", "0", "-an"]),
}

LOSSY = {"mp3", "ogg", "opus", "m4a", "aac", "mp4", "mkv", "webm", "mov", "avi"}


def _notes(source: str, target: str) -> str:
    if source in VIDEO and target in AUDIO:
        return "Estrae solo la traccia audio"
    if target == "gif":
        return "Animazione senza audio, max 640 px a 12 fps: adatta a clip brevi"
    if target in LOSSY:
        return "Compressione con perdita: qualità alta ma non identica all'originale"
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
        ]

    def probe(self) -> list[Conversion]:
        try:
            out = subprocess.run(
                [self.binary(), "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        encoders = {line.split()[1] for line in out.splitlines()
                    if len(line.split()) > 1 and line.startswith(" ") and "=" not in line}
        codecs = AUDIO_CODECS | VIDEO_CODECS
        return [c for c in self.declared() if set(codecs[c.target][0]) <= encoders]

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

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        target = conversion.target
        if target in AUDIO_CODECS:
            codec_args = ["-vn", *AUDIO_CODECS[target][1]]
        else:
            codec_args = VIDEO_CODECS[target][1]

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
