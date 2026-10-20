import zipfile

from anyfile.core.detector import detect, same_family


def write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_signature_wins_over_extension(tmp_path):
    info = detect(write(tmp_path, "photo.jpg", b"\x89PNG\r\n\x1a\n" + b"\0" * 32))
    assert info.format.id == "png"
    assert info.detected_by == "signature"
    assert info.extension_mismatch


def test_common_signatures(tmp_path):
    cases = {
        "a.gif": (b"GIF89a" + b"\0" * 10, "gif"),
        "a.webp": (b"RIFF\0\0\0\0WEBPVP8 ", "webp"),
        "a.wav": (b"RIFF\0\0\0\0WAVEfmt ", "wav"),
        "a.pdf": (b"%PDF-1.7\n", "pdf"),
        "a.flac": (b"fLaC\0\0\0\x22", "flac"),
        "a.ogg": (b"OggS\0\x02" + b"\0" * 22 + b"\x01vorbis", "ogg"),
        "a.opus": (b"OggS\0\x02" + b"\0" * 22 + b"OpusHead", "opus"),
        "a.mp3": (b"ID3\x04\0\0\0\0\0\0", "mp3"),
        "a.m4a": (b"\0\0\0\x18ftypM4A \0\0\0\0", "m4a"),
        "a.mp4": (b"\0\0\0\x18ftypisom\0\0\0\0", "mp4"),
        "a.mov": (b"\0\0\0\x14ftypqt  \0\0\0\0", "mov"),
        "a.webm": (b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x84webm", "webm"),
        "a.rtf": (b"{\\rtf1\\ansi ciao}", "rtf"),
    }
    for name, (data, expected) in cases.items():
        assert detect(write(tmp_path, name, data)).format.id == expected, name


def test_office_open_xml_and_opendocument(tmp_path):
    docx = tmp_path / "x.zip"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    assert detect(docx).format.id == "docx"

    odt = tmp_path / "y.bin"
    with zipfile.ZipFile(odt, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", "<office:document/>")
    assert detect(odt).format.id == "odt"


def test_text_files_use_extension_or_content(tmp_path):
    assert detect(write(tmp_path, "a.md", b"# Title\n")).format.id == "md"
    assert detect(write(tmp_path, "a.csv", b"a,b\n1,2\n")).format.id == "csv"
    assert detect(write(tmp_path, "page", b"<!DOCTYPE html><html></html>")).format.id == "html"
    assert detect(write(tmp_path, "README", "Text with àccents\n".encode())).format.id == "txt"


def test_unrecognized_and_empty(tmp_path):
    empty = detect(write(tmp_path, "empty.png", b""))
    assert empty.format is None and "empty" in empty.reason
    junk = detect(write(tmp_path, "data.xyz", bytes(range(256)) * 4))
    assert junk.format is None


def test_same_family():
    assert same_family("mp4", "m4a")
    assert same_family("mkv", "webm")
    assert not same_family("png", "jpg")
