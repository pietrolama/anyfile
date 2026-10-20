import subprocess

import pytest
from conftest import needs

from anyfile import cli
from anyfile.core.executor import Executor
from anyfile.models.conversion import Quality
from anyfile.models.job import Job


@pytest.mark.parametrize("source,target", [("png", "png"), ("wav", "wav"), ("wav", "flac"),
                                           ("png", "tiff"), ("md", "docx"), ("pdf", "txt")])
def test_lossless_targets_offer_no_presets(registry, source, target):
    conv = registry.find(source, target) or registry.find("mp3", target) or registry.find("jpg", target)
    if conv is None:
        pytest.skip("conversione non disponibile")
    assert registry.presets(conv) == {}


@pytest.mark.parametrize("source,target", [("png", "jpg"), ("png", "webp"), ("wav", "mp3"),
                                           ("wav", "opus"), ("mp4", "webm"), ("mp4", "gif")])
def test_lossy_targets_offer_three_described_presets(registry, source, target):
    conv = registry.find(source, target)
    if conv is None:
        pytest.skip("conversione non disponibile")
    presets = registry.presets(conv)
    assert list(presets) == list(Quality)
    assert all(presets.values())


def test_quality_parse():
    assert Quality.parse("Massima") is Quality.MAX
    assert Quality.parse("leggero") is Quality.SMALL
    assert Quality.parse("balanced") is Quality.BALANCED
    assert Quality.parse("enorme") is None


def _sizes(registry, src, target, tmp_path):
    sizes = {}
    for q in Quality:
        out = Executor(registry).run(Job(src, target, output_dir=tmp_path / q.value, quality=q))
        sizes[q] = out.stat().st_size
    return sizes


@needs("magick")
def test_image_presets_change_size(registry, tmp_path):
    src = tmp_path / "foto.png"
    subprocess.run(["magick", "-size", "400x300", "plasma:fractal", str(src)], check=True)
    for target in ("jpg", "webp"):
        s = _sizes(registry, src, target, tmp_path / target)
        assert s[Quality.MAX] > s[Quality.BALANCED] > s[Quality.SMALL], (target, s)


@needs("ffmpeg")
def test_media_presets_change_size(registry, tmp_path):
    wav = tmp_path / "rumore.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=3", str(wav)], check=True)
    s = _sizes(registry, wav, "mp3", tmp_path / "mp3")
    assert s[Quality.MAX] > s[Quality.BALANCED] > s[Quality.SMALL], s

    video = tmp_path / "video.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=2:s=1280x960:r=25",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    out = Executor(registry).run(Job(video, "webm", output_dir=tmp_path / "w", quality=Quality.SMALL))
    height = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                             "stream=height", "-of", "csv=p=0", str(out)],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert height == "720"


def test_cli_rejects_unknown_quality(sample, capsys):
    assert cli.main(["convert", str(sample("md")), "-t", "html", "-q", "enorme"]) == 2
    assert "qualità sconosciuta" in capsys.readouterr().err


@needs("magick")
def test_compress_jpeg_keeps_original_and_is_smaller(registry, tmp_path):
    src = tmp_path / "foto.jpg"
    subprocess.run(["magick", "-size", "800x600", "plasma:fractal", "-quality", "98", str(src)],
                   check=True)
    original = src.read_bytes()
    out = Executor(registry).run(Job(src, "jpg", quality=Quality.SMALL, overwrite=True))
    assert out.name == "foto-compresso.jpg"
    assert out.stat().st_size < src.stat().st_size
    assert src.read_bytes() == original


@needs("magick")
def test_compress_without_gain_is_discarded(registry, tmp_path):
    from anyfile.core.errors import NothingGained
    src = tmp_path / "piccola.jpg"
    subprocess.run(["magick", "-size", "800x600", "plasma:fractal", "-quality", "30", str(src)],
                   check=True)
    with pytest.raises(NothingGained, match="già compatto"):
        Executor(registry).run(Job(src, "jpg", quality=Quality.BALANCED))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["piccola.jpg"]


def test_compress_offers_no_max_preset(registry):
    conv = registry.find("jpg", "jpg")
    if conv is None:
        pytest.skip("ImageMagick non disponibile")
    assert list(registry.presets(conv)) == [Quality.BALANCED, Quality.SMALL]


def test_lossless_format_cannot_be_compressed(registry, sample):
    from anyfile.core.planner import PlanError
    with pytest.raises(PlanError, match="non si può comprimere"):
        Executor(registry).run(Job(sample("png"), "png"))


def test_queue_reports_unchanged(registry, tmp_path):
    if registry.find("jpg", "jpg") is None:
        pytest.skip("ImageMagick non disponibile")
    from anyfile.core.jobs import JobQueue
    from anyfile.models.job import JobStatus
    src = tmp_path / "piccola.jpg"
    subprocess.run(["magick", "-size", "400x300", "plasma:fractal", "-quality", "30", str(src)],
                   check=True)
    queue = JobQueue(Executor(registry))
    job = queue.submit(src, "jpg")
    queue.wait()
    assert job.status is JobStatus.UNCHANGED and "già compatto" in job.message
