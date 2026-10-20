from pathlib import Path

import pytest
from test_registry import FakeEngine

from anyfile.core import formats
from anyfile.core.planner import PlanError, plan
from anyfile.core.registry import Registry
from anyfile.engines.base import pairs
from anyfile.models.file_info import FileInfo


def info(fmt_id, name="file"):
    return FileInfo(Path(name), formats.get(fmt_id) if fmt_id else None, 10, "firma")


@pytest.fixture
def reg():
    return Registry([
        FakeEngine("img", "Img", pairs("x", ["png"], ["jpg"])),
        FakeEngine("office", "LibreOffice", pairs("x", ["docx"], ["pdf"]), available=False),
    ])


def test_direct_plan(reg):
    p = plan(info("png"), "jpeg", reg)  # extension alias
    assert p.route.target == "jpg" and not p.route.is_chain
    assert p.target_format.ext == "jpg"


def test_unknown_source(reg):
    with pytest.raises(PlanError, match="Unrecognized format"):
        plan(info(None, "x.bin"), "jpg", reg)


def test_same_format(reg):
    with pytest.raises(PlanError, match="is already PNG"):
        plan(info("png"), "png", reg)


def test_missing_engine_is_explained(reg):
    with pytest.raises(PlanError, match=r"requires LibreOffice.*apt install pkg-office"):
        plan(info("docx"), "pdf", reg)


def test_unsupported(reg):
    with pytest.raises(PlanError, match="is not supported"):
        plan(info("png"), "mp3", reg)
