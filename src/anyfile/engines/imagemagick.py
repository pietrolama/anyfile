from __future__ import annotations

import re
import subprocess
from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, compressions, pairs
from anyfile.models.conversion import Conversion, Presets, Quality

# id ANYFILE → nome del coder ImageMagick
CODERS = {
    "png": "PNG", "jpg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP",
    "tiff": "TIFF", "ico": "ICO", "avif": "AVIF", "heic": "HEIC", "pdf": "PDF",
}
IMAGES = [f for f in CODERS if f != "pdf"]

# Formati che conservano più fotogrammi/pagine; per gli altri si usa il primo.
MULTI_FRAME = {"gif", "webp", "tiff", "pdf"}
# Formati senza trasparenza: lo sfondo trasparente diventa bianco invece che nero.
NO_ALPHA = {"jpg", "bmp"}

# Solo i formati con perdita hanno preset: per PNG, BMP, TIFF... non cambierebbero nulla.
# qualità → (valore di -quality, rimozione dei metadati)
QUALITY: dict[str, dict[Quality, tuple[int, bool]]] = {
    "jpg": {Quality.MAX: (95, False), Quality.BALANCED: (85, False), Quality.SMALL: (70, True)},
    "webp": {Quality.MAX: (95, False), Quality.BALANCED: (80, False), Quality.SMALL: (60, True)},
}

_FORMAT_LINE = re.compile(r"^\s*([A-Z0-9-]+)\*?\s+\S+\s+([r-])([w-])[+-]")


def _notes(source: str, target: str) -> str:
    if source in ("gif", "webp", "tiff") and target not in MULTI_FRAME:
        return "Per immagini animate o multipagina viene salvato solo il primo fotogramma"
    if target in NO_ALPHA:
        return "Le aree trasparenti diventano bianche"
    if target == "ico":
        return "Icona con le dimensioni 16–256 px"
    if target == "pdf":
        return "Un'immagine per pagina"
    return ""


class ImageMagickEngine(Engine):
    name = "imagemagick"
    label = "ImageMagick"
    package = "imagemagick"
    # ImageMagick 7 usa "magick", la 6 (Ubuntu 22.04/24.04) "convert".
    requires = (("magick", "convert"),)

    def declared(self) -> list[Conversion]:
        return [*pairs(self.name, IMAGES, [*IMAGES, "pdf"], _notes),
                *compressions(self.name, QUALITY)]

    def probe(self) -> list[Conversion]:
        try:
            out = subprocess.run(
                [self.binary(), "-list", "format"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        readable, writable = set(), set()
        for line in out.splitlines():
            if m := _FORMAT_LINE.match(line):
                if m.group(2) == "r":
                    readable.add(m.group(1))
                if m.group(3) == "w":
                    writable.add(m.group(1))
        return [c for c in self.declared()
                if CODERS[c.source] in readable and CODERS[c.target] in writable]

    def presets(self, target: str) -> Presets:
        return {
            q: f"Qualità {value}" + (", senza metadati (EXIF, GPS)" if strip else "")
            for q, (value, strip) in QUALITY.get(target, {}).items()
        }

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        target = conversion.target
        ctx.progress(None)
        # src è un collegamento con nome sicuro: la sintassi [0] non può collidere col nome.
        args = [self.binary(), str(src) if target in MULTI_FRAME else f"{src}[0]", "-auto-orient"]
        if target in NO_ALPHA:
            args += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
        if target in QUALITY:
            value, strip = QUALITY[target][ctx.quality]
            args += ["-quality", str(value)]
            if strip:
                args += ["-strip"]
        if target == "ico":
            args += ["-define", "icon:auto-resize=256,128,64,48,32,16"]
        args.append(f"{CODERS[target]}:{dst}")
        ctx.runner.run(args, tool="ImageMagick")
