"""Conversioni concatenate: regole del grafo ed esecuzione reale passo per passo."""

import zipfile

import pytest
from conftest import needs

from anyfile.core import formats
from anyfile.core.errors import AnyfileError
from anyfile.core.executor import Executor
from anyfile.core.registry import Registry
from anyfile.engines.base import pairs
from anyfile.models.conversion import Conversion
from anyfile.models.job import Job
from test_registry import FakeEngine


def fake_registry(*edges):
    convs = [c for s, targets in edges for c in pairs("x", [s], targets)]
    return Registry([FakeEngine("f", "F", convs)])


def test_direct_conversion_wins_over_chain():
    reg = fake_registry(("docx", ["pdf", "html"]), ("html", ["pdf"]))
    route = reg.route("docx", "pdf")
    assert not route.is_chain


def test_chain_when_no_direct_conversion():
    reg = fake_registry(("doc", ["docx"]), ("docx", ["epub"]))
    route = reg.route("doc", "epub")
    assert route.is_chain and route.via == ("docx",)


def test_lossy_intermediates_are_never_used():
    # MP4 → GIF → PNG degraderebbe due volte: niente catena.
    reg = fake_registry(("mp4", ["gif"]), ("gif", ["png"]))
    assert reg.route("mp4", "png") is None


def test_no_chain_that_invents_text_from_images():
    # PNG → PDF → testo darebbe un file vuoto senza OCR.
    reg = fake_registry(("png", ["pdf"]), ("pdf", ["txt"]))
    assert reg.route("png", "txt") is None


def test_multi_output_only_as_last_step():
    reg = Registry([
        FakeEngine("a", "A", pairs("x", ["docx"], ["pdf"])),
        FakeEngine("b", "B", [Conversion("pdf", "png", "x", "", True)]),
        FakeEngine("c", "C", pairs("x", ["png"], ["webp"])),
    ])
    assert reg.route("docx", "png").via == ("pdf",)
    assert reg.route("pdf", "webp") is None  # pdf → (più png) → webp: intermedio multiplo


def test_best_intermediate_has_fewest_declared_losses():
    from anyfile.models.conversion import Conversion
    engine = FakeEngine("f", "F", [
        Conversion("epub", "md", "f", "perde le immagini"), Conversion("md", "pdf", "f", ""),
        Conversion("epub", "docx", "f", ""), Conversion("docx", "pdf", "f", ""),
    ])
    assert Registry([engine]).route("epub", "pdf").via == ("docx",)


def test_chain_notes_accumulate():
    from anyfile.models.conversion import Conversion
    engine = FakeEngine("f", "F", [Conversion("pdf", "txt", "f", "Solo il testo"),
                                   Conversion("txt", "docx", "f", "Layout diverso")])
    assert Registry([engine]).route("pdf", "docx").notes == "Solo il testo; Layout diverso"


def test_real_registry_chains_follow_the_rules():
    reg = Registry()
    for fmt in formats.FORMATS:
        for route in reg.routes(fmt.id):
            assert len(route.steps) <= 2
            if route.is_chain:
                assert route.via[0] not in formats.LOSSY_FORMATS
                assert not route.steps[0].multi_output
                assert reg.find(route.source, route.target) is None


# --- esecuzione reale ------------------------------------------------------

@pytest.mark.slow
@needs("soffice", "pdftoppm")
def test_docx_to_png_via_pdf(registry, sample):
    route = registry.route("docx", "png")
    assert route and route.via == ("pdf",)
    out = Executor(registry).run(Job(sample("docx"), "png"))
    assert out.suffix == ".png" and out.stat().st_size > 0
    assert not list(out.parent.glob(".anyfile-*")), "intermedi non rimossi"


@pytest.mark.slow
@needs("soffice", "pandoc")
def test_rtf_to_markdown_via_docx(registry, tmp_path):
    rtf = tmp_path / "lettera.rtf"
    rtf.write_text(r"{\rtf1\ansi {\b Titolo}\par Testo della lettera.\par}")
    out = Executor(registry).run(Job(rtf, "md"))
    assert out.name == "lettera.md"
    assert "Testo della lettera" in out.read_text()


@pytest.mark.slow
@needs("soffice", "pdftoppm")
def test_xlsx_to_png_progress_is_monotonic(registry, sample, tmp_path):
    xlsx = sample("csv")
    seen = []
    Executor(registry).run(Job(xlsx, "png"), seen.append)
    values = [v for v in seen if v is not None]
    assert values == sorted(values)


@pytest.mark.slow
@needs("soffice")
def test_failing_step_is_named(registry, tmp_path):
    broken = tmp_path / "rotto.docx"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "non è xml valido")
    with pytest.raises(AnyfileError, match=r"Passaggio 1 di 2 \(Word DOCX → PDF\)"):
        Executor(registry).run(Job(broken, "png"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rotto.docx"]
