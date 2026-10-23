"""STRATUM: inspection and extraction of audio files (MP3, FLAC, M4A, OGG, OPUS)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import needs
from anyfile import stratum
from anyfile.core.detector import detect
from anyfile.core.executor import Executor
from anyfile.models.component import Kind
from anyfile.models.job import Job
from anyfile.stratum import media


def _extract(registry, path, component_id, **kwargs):
    job = Job(path, "", tool=stratum.EXTRACT, option=component_id, **kwargs)
    return job, Executor(registry).run(job)


@pytest.fixture
def sample_cover_png(tmp_path) -> Path:
    cover = tmp_path / "cover.png"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=120x120:d=1",
        "-vframes", "1", str(cover),
    ], check=True)
    return cover


@pytest.fixture
def sample_cover_jpg(tmp_path) -> Path:
    cover = tmp_path / "cover.jpg"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=120x120:d=1",
        "-vframes", "1", str(cover),
    ], check=True)
    return cover


@pytest.fixture
def mp3_with_cover(tmp_path, sample_cover_jpg) -> Path:
    path = tmp_path / "track.mp3"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1.5",
        "-i", str(sample_cover_jpg),
        "-map", "0:0", "-map", "1:0",
        "-c:a", "libmp3lame", "-c:v", "mjpeg",
        "-id3v2_version", "3",
        "-metadata", "title=Sample Track",
        "-metadata:s:a:0", "language=eng",
        "-metadata:s:v:0", "title=Album cover",
        str(path),
    ], check=True)
    return path


@pytest.fixture
def flac_with_cover(tmp_path, sample_cover_png) -> Path:
    path = tmp_path / "track.flac"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1.2",
        "-i", str(sample_cover_png),
        "-map", "0:0", "-map", "1:0",
        "-c:a", "flac", "-c:v", "png",
        "-disposition:v", "attached_pic",
        str(path),
    ], check=True)
    return path


@pytest.fixture
def m4a_with_cover_and_lyrics(tmp_path, sample_cover_jpg) -> Path:
    lyrics = tmp_path / "lyrics.srt"
    lyrics.write_text("1\n00:00:00,100 --> 00:00:01,000\nSinging in the rain\n")
    path = tmp_path / "audiobook.m4a"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2",
        "-i", str(sample_cover_jpg),
        "-i", str(lyrics),
        "-map", "0:0", "-map", "1:0", "-map", "2:0",
        "-c:a", "aac", "-c:v", "mjpeg", "-disposition:v", "attached_pic",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=ita", "-metadata:s:s:0", "title=Lyrics",
        str(path),
    ], check=True)
    return path


def test_sources_includes_audio_formats():
    for fmt in ("mp3", "flac", "m4a", "ogg", "opus"):
        assert fmt in media.SOURCES


def test_audio_anatomy_unit():
    probe = {
        "format": {"duration": "120.5"},
        "streams": [
            {
                "index": 0, "codec_type": "audio", "codec_name": "flac",
                "channels": 2, "sample_rate": "44100", "tags": {"language": "ita"},
            },
            {
                "index": 1, "codec_type": "video", "codec_name": "png",
                "width": 300, "height": 300, "disposition": {"attached_pic": 1},
            },
        ],
    }
    a = media.anatomy(probe, "flac")
    assert len(a.components) == 2
    audio, cover = a.components
    assert audio.kind is Kind.AUDIO and audio.ext == "flac" and audio.language == "ita"
    assert cover.kind is Kind.COVER and cover.ext == "png" and cover.details == "300×300"
    assert a.duration == pytest.approx(120.5)


@needs("ffmpeg", "ffprobe")
def test_mp3_probe_and_cover_extraction(registry, mp3_with_cover):
    info = detect(mp3_with_cover)
    a = stratum.explode(info, mp3_with_cover, registry)
    assert len(a.components) == 2
    audio = a.get("0")
    cover = a.get("1")

    assert audio.kind is Kind.AUDIO and audio.ext == "mp3"
    assert cover.kind is Kind.COVER and cover.ext == "jpg"

    job_cover, out_cover = _extract(registry, mp3_with_cover, "1")
    assert out_cover.name == "track.cover.jpg"
    assert out_cover.is_file() and out_cover.stat().st_size > 0

    job_audio, out_audio = _extract(registry, mp3_with_cover, "0")
    assert out_audio.name.endswith(".mp3")
    assert out_audio.is_file() and out_audio.stat().st_size > 0


@needs("ffmpeg", "ffprobe")
def test_flac_probe_and_cover_extraction(registry, flac_with_cover):
    info = detect(flac_with_cover)
    a = stratum.explode(info, flac_with_cover, registry)
    assert len(a.components) == 2
    audio = a.get("0")
    cover = a.get("1")

    assert audio.kind is Kind.AUDIO and audio.ext == "flac"
    assert cover.kind is Kind.COVER and cover.ext == "png"

    _job_cover, out_cover = _extract(registry, flac_with_cover, "1")
    assert out_cover.name == "track.cover.png"
    assert out_cover.is_file() and out_cover.stat().st_size > 0

    _job_audio, out_audio = _extract(registry, flac_with_cover, "0")
    assert out_audio.name == "track.audio0.flac"
    assert out_audio.is_file() and out_audio.stat().st_size > 0


@needs("ffmpeg", "ffprobe")
def test_m4a_with_cover_and_timed_lyrics(registry, m4a_with_cover_and_lyrics):
    info = detect(m4a_with_cover_and_lyrics)
    a = stratum.explode(info, m4a_with_cover_and_lyrics, registry)

    kinds = {c.kind for c in a.components}
    assert Kind.AUDIO in kinds
    assert Kind.COVER in kinds
    assert Kind.SUBTITLE in kinds

    cover = a.of(Kind.COVER)[0]
    sub = a.of(Kind.SUBTITLE)[0]

    _job_cover, out_cover = _extract(registry, m4a_with_cover_and_lyrics, cover.id)
    assert out_cover.name == "audiobook.cover.jpg"
    assert out_cover.is_file() and out_cover.stat().st_size > 0

    _job_sub, out_sub = _extract(registry, m4a_with_cover_and_lyrics, sub.id)
    assert out_sub.name == "audiobook.ita.srt"
    assert "Singing in the rain" in out_sub.read_text()


@needs("ffmpeg", "ffprobe")
def test_audio_conversion_during_extraction(registry, mp3_with_cover):
    _job, out_flac = _extract(registry, mp3_with_cover, "0:flac")
    assert out_flac.name.endswith(".flac")
    assert out_flac.is_file() and out_flac.stat().st_size > 0
