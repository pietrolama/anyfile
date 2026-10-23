"""STRATUM: the tracks of a video, read with FFprobe and extracted without re-encoding."""

from __future__ import annotations

import hashlib
import subprocess

import pytest

from conftest import needs
from anyfile import cli, stratum
from anyfile.core import history as hist
from anyfile.core.detector import detect
from anyfile.core.errors import AnyfileError
from anyfile.core.executor import Executor
from anyfile.models.component import Kind
from anyfile.models.job import Job
from anyfile.stratum import media


def _stream(index, kind, codec, **extra):
    return {"index": index, "codec_type": kind, "codec_name": codec, **extra}


PROBE = {
    "format": {"duration": "5532.4"},
    "streams": [
        _stream(0, "video", "hevc", width=1920, height=1080, avg_frame_rate="24000/1001"),
        _stream(1, "audio", "aac", channels=2, sample_rate="48000", tags={"language": "ita"},
                disposition={"default": 1}),
        _stream(2, "audio", "ac3", channels=6, channel_layout="5.1(side)", sample_rate="48000",
                tags={"LANGUAGE": "eng", "title": "Director\x1b[31m commentary"}),
        _stream(3, "audio", "pcm_s16le", channels=1, tags={"language": "und"}),
        _stream(4, "audio", "pcm_s24be", tags={"language": "../../x"}),
        _stream(5, "subtitle", "subrip", tags={"language": "ita"}),
        _stream(6, "subtitle", "hdmv_pgs_subtitle", tags={"language": "eng"}, disposition={"forced": 1}),
        _stream(7, "subtitle", "dvd_subtitle"),
        _stream(8, "attachment", "ttf", tags={"filename": "font.ttf"}),
        _stream(9, "data", "bin_data"),
        _stream(10, "video", "png", width=600, height=600, disposition={"attached_pic": 1}),
        _stream(11, "video", "bmp", disposition={"attached_pic": 1}),
        {"codec_type": "audio"},  # no index: ignored
        "not a stream",
    ],
}


def test_anatomy_lists_the_tracks_and_leaves_out_the_rest():
    a = media.anatomy(PROBE, "mkv")
    assert [c.id for c in a.components] == ["0", "1", "2", "3", "4", "5", "6", "7", "10", "11"]
    assert [c.kind for c in a.components[:2]] == [Kind.VIDEO, Kind.AUDIO]
    assert a.summary == "Matroska MKV · 1:32:12"
    assert a.duration == pytest.approx(5532.4)


def test_each_codec_goes_to_a_container_that_holds_it_as_it_is():
    a = media.anatomy(PROBE, "mkv")
    assert {c.id: c.ext for c in a.components} == {
        "0": "mkv", "1": "m4a", "2": "ac3", "3": "wav", "4": "mka", "5": "srt", "6": "sup",
        "7": "mks", "10": "png", "11": ""}
    # An MP4 video stays MP4 when the codec allows it.
    mp4 = media.anatomy({"streams": [_stream(0, "video", "h264"), _stream(1, "video", "vp9"),
                                     _stream(2, "subtitle", "mov_text")]}, "mp4")
    assert [c.ext for c in mp4.components] == ["mp4", "mkv", "srt"]
    assert media.codec_args(mp4.components[2]) == ["-c:s", "srt"]


def test_tracks_can_be_converted_to_the_formats_ffmpeg_can_write():
    a = media.anatomy(PROBE, "mkv")
    available = {"mp3", "flac", "wav", "m4a"}  # e.g. a build without Opus and Vorbis
    assert media.targets(a.get("1"), available) == ["m4a", "mp3", "flac", "wav"]
    assert media.targets(a.get("2"), available) == ["ac3", "mp3", "m4a", "flac", "wav"]
    assert media.targets(a.get("5"), available) == ["srt", "ass", "vtt"]
    assert media.targets(a.get("6"), available) == ["sup"]  # images: kept as they are
    assert media.targets(a.get("0"), available) == ["mkv"]
    assert media.targets(a.get("11"), available) == []
    surround = a.get("2")
    assert media.codec_args(surround, "mp3")[-2:] == ["-ac", "2"]
    assert media.codec_args(surround, "opus")[-2] == "-af"
    assert media.codec_args(a.get("1"), "flac") == ["-c:a", "flac"]
    assert media.codec_args(a.get("5"), "vtt") == ["-c:s", "webvtt"]
    assert stratum.parse_option("1:mp3") == ("1", "mp3") and stratum.parse_option("1") == ("1", "")


def test_texts_from_the_file_are_cleaned_and_languages_validated():
    a = media.anatomy(PROBE, "mkv")
    ita, commentary, und, bogus = a.get("1"), a.get("2"), a.get("3"), a.get("4")
    assert (ita.language, ita.short, ita.default) == ("ita", "ITA", True)
    assert commentary.language == "eng"  # tag names are not case-sensitive
    assert commentary.title == "Director [31m commentary"
    assert und.language == "" and und.short == "PCM_S16LE"
    assert bogus.language == ""
    long_title = media.anatomy({"streams": [_stream(0, "audio", "aac", tags={"title": "x" * 500})]}, "mkv")
    assert len(long_title.components[0].title) == media.TITLE_MAX


def test_details_are_short_and_readable():
    a = media.anatomy(PROBE, "mkv")
    assert a.get("0").details == "1920×1080 · 23.976 fps"
    assert a.get("1").details == "2 channels · 48 kHz"
    assert a.get("2").details == "5.1 · 48 kHz"
    assert a.get("0").codec == "H.265" and a.get("6").codec == "PGS"


def test_a_cover_in_an_unsupported_image_format_is_shown_but_not_extractable():
    cover = media.anatomy(PROBE, "mkv").get("11")
    assert cover.kind is Kind.COVER and not cover.extractable and cover.reason


def test_result_names_follow_the_conventions_of_players():
    a = media.anatomy(PROBE, "mkv")
    assert stratum.result_name("film", a.get("1")) == "film.ita"
    assert stratum.result_name("film", a.get("6")) == "film.eng.forced"
    assert stratum.result_name("film", a.get("3")) == "film.audio3"
    assert stratum.result_name("film", a.get("10")) == "film.cover"


# --- with the real engines --------------------------------------------------------

@pytest.fixture
def movie(tmp_path):
    """Two audio tracks, two subtitle tracks (one forced); the audio starts before zero,
    as AAC does, which is what used to shift extracted subtitles."""
    for code, text in (("it", "Ciao"), ("en", "Hello")):
        (tmp_path / f"{code}.srt").write_text(f"1\n00:00:00,500 --> 00:00:01,500\n{text}\n")
    path = tmp_path / "-film con spazi [1].mkv"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=2:s=96x64:r=10",
        "-f", "lavfi", "-i", "sine=d=2", "-f", "lavfi", "-i", "sine=d=2:f=880",
        "-i", str(tmp_path / "it.srt"), "-i", str(tmp_path / "en.srt"),
        "-map", "0", "-map", "1", "-map", "2", "-map", "3", "-map", "4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a:0", "aac", "-c:a:1", "libopus", "-c:s", "srt",
        "-metadata:s:a:0", "language=ita", "-metadata:s:a:1", "language=eng",
        "-metadata:s:s:0", "language=ita", "-metadata:s:s:1", "language=eng",
        "-disposition:s:1", "forced", "--", str(path)], check=True, capture_output=True)
    return path


def _extract(registry, path, component_id, **kwargs):
    job = Job(path, "", tool=stratum.EXTRACT, option=component_id, **kwargs)
    return job, Executor(registry).run(job)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@needs("ffmpeg", "ffprobe")
def test_explode_reads_the_tracks_of_a_real_file(registry, movie):
    a = stratum.explode(detect(movie), movie, registry)
    assert [(c.kind, c.short) for c in a.components] == [
        (Kind.VIDEO, "H.264"), (Kind.AUDIO, "ITA"), (Kind.AUDIO, "ENG"),
        (Kind.SUBTITLE, "ITA"), (Kind.SUBTITLE, "ENG")]
    assert a.get("4").forced


@needs("ffmpeg", "ffprobe")
def test_audio_is_extracted_without_re_encoding_and_the_original_stays(registry, movie):
    before = _digest(movie)
    job, out = _extract(registry, movie, "1")
    assert out.name == "-film con spazi [1].ita.m4a"
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
                              "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    assert streams == ["aac,audio"]
    assert job.target == "m4a" and job.output_size == out.stat().st_size
    assert _digest(movie) == before
    # No temporary folder left behind.
    assert not [p for p in movie.parent.iterdir() if p.name.startswith(".anyfile-")]


@needs("ffmpeg", "ffprobe")
def test_a_track_is_converted_while_extracted_and_checked(registry, movie):
    job, out = _extract(registry, movie, stratum.option("1", "mp3"))
    assert out.name.endswith(".ita.mp3") and job.target == "mp3"
    assert job.applied_quality is not None
    _job, vtt = _extract(registry, movie, "3:vtt")
    assert vtt.read_text().startswith("WEBVTT") and "00:00.500 --> 00:01.500" in vtt.read_text()
    with pytest.raises(AnyfileError, match="cannot be saved as MP3"):
        _extract(registry, movie, "0:mp3")


@needs("ffmpeg", "ffprobe")
def test_extracted_subtitles_keep_the_timing_of_the_video(registry, movie):
    _job, out = _extract(registry, movie, "4")
    assert out.name.endswith(".eng.forced.srt")
    assert "00:00:00,500 --> 00:00:01,500" in out.read_text()


@needs("ffmpeg", "ffprobe")
def test_an_existing_file_is_never_overwritten_by_default(registry, movie):
    taken = movie.with_name(f"{movie.stem}.ita.srt")
    taken.write_text("mine")
    _job, out = _extract(registry, movie, "3")
    assert out.name == f"{movie.stem}.ita (1).srt"
    assert taken.read_text() == "mine"


@needs("ffmpeg", "ffprobe")
def test_unknown_tracks_and_unsupported_files_fail_clearly(registry, movie, tmp_path):
    with pytest.raises(AnyfileError, match="has no track 9"):
        _extract(registry, movie, "9")
    text = tmp_path / "notes.txt"
    text.write_text("not a video\n")
    with pytest.raises(AnyfileError, match="cannot look inside"):
        _extract(registry, text, "0")


@needs("ffmpeg", "ffprobe")
def test_a_file_that_is_not_what_it_claims_is_refused(registry, tmp_path):
    fake = tmp_path / "fake.mkv"
    fake.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 64)
    with pytest.raises(AnyfileError):
        stratum.explode(detect(fake), fake, registry)


def test_the_history_describes_extractions():
    entry = hist.Entry(1, hist.datetime.now(hist.timezone.utc), hist.Path("/v/film.mkv"), "mkv", 1000,
                       "m4a", (), None, hist.JobStatus.DONE, "", "", hist.Path("/v/film.ita.m4a"), 400,
                       None, False, tool=stratum.EXTRACT, option="1")
    assert hist.describe(entry) == "Extract Matroska MKV · track 1"
    assert hist.describe_result(entry) == "400 B"
    converted = hist.Entry(**{**entry.__dict__, "option": "1:mp3"})
    assert hist.describe(converted) == "Extract Matroska MKV · track 1 → MP3"


@needs("ffmpeg", "ffprobe")
def test_cli_lists_and_extracts(movie, capsys):
    assert cli.main(["explode", str(movie)]) == 0
    out = capsys.readouterr().out
    assert "Subtitles" in out and "ENG  SubRip  forced  → .srt .ass .vtt" in out
    assert cli.main(["explode", str(movie), "-x", "2", "3"]) == 0
    assert movie.with_name(f"{movie.stem}.eng.opus").is_file()
    assert movie.with_name(f"{movie.stem}.ita.srt").is_file()
    assert cli.main(["explode", str(movie), "-x", "42"]) == 2
    assert cli.main(["explode", str(movie), "-x", "1:xyz"]) == 2
    assert cli.main(["explode", str(movie), "-x", "1:wav"]) == 0
    assert movie.with_name(f"{movie.stem}.ita.wav").is_file()
