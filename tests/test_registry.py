from dataclasses import replace

from conftest import ALWAYS_PRESENT
from pathlib import Path

from anyfile.core.registry import Registry
from anyfile.engines.base import Engine, pairs


class FakeEngine(Engine):
    def __init__(self, name, label, convs, available=True):
        super().__init__()
        self.name, self.label, self.package = name, label, f"pkg-{name}"
        self.requires = ((ALWAYS_PRESENT,),) if available else ((f"anyfile-missing-{name}",),)
        self._declared = convs

    def declared(self):
        return [replace(c, engine=self.name) for c in self._declared]

    def convert(self, conversion, src: Path, dst: Path, ctx):  # pragma: no cover
        raise NotImplementedError


def test_only_installed_engines_provide_targets():
    media = FakeEngine("media", "Media", pairs("x", ["mp3"], ["wav", "flac"]))
    office = FakeEngine("office", "Office", pairs("x", ["docx"], ["pdf"]), available=False)
    reg = Registry([media, office])
    assert [c.target for c in reg.targets("mp3")] == ["flac", "wav"]
    assert reg.targets("docx") == []
    assert reg.find("docx", "pdf") is None
    assert reg.missing_engines_for("docx", "pdf") == [office]
    assert reg.unlockable_targets("docx") == {"Office": ["pdf"]}


def test_first_engine_has_priority():
    a = FakeEngine("a", "A", pairs("x", ["png"], ["jpg"]))
    b = FakeEngine("b", "B", pairs("x", ["png"], ["jpg", "webp"]))
    reg = Registry([a, b])
    assert reg.find("png", "jpg").engine == "a"
    assert reg.find("png", "webp").engine == "b"


def test_status_reports_missing_binaries():
    reg = Registry([FakeEngine("z", "Zeta", [], available=False)])
    (status,) = reg.status()
    assert not status.available
    assert status.missing == ("anyfile-missing-z",)


def test_compressions_only_for_lossy_formats():
    # Stesso formato in uscita solo dove un preset riduce davvero il file.
    reg = Registry()
    for engine in reg.engines:
        for c in engine.declared():
            if c.is_compression:
                presets = engine.presets(c.target)
                assert presets, c
    for c in (reg.find("png", "png"), reg.find("wav", "wav"), reg.find("flac", "flac")):
        assert c is None
