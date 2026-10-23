# ANYFILE

[![Test](https://github.com/pietrolama/anyfile/actions/workflows/test.yml/badge.svg)](https://github.com/pietrolama/anyfile/actions/workflows/test.yml)

*[Leggi in italiano](README.it.md)*

A local file converter for Linux, made for KDE Plasma on Debian/Ubuntu. Right-click a
file in Dolphin and a wheel under the pointer shows what you can do with it: convert
it, compress it, pick the quality. You choose the result, not the program: ANYFILE
detects the format, offers only the conversions the installed engines can really
carry out, runs them safely and checks the file it produces. With **STRATUM**, it looks
inside compound files: video tracks, audio covers, PDF images and attachments, ZIP
archive members, or animated GIF / multi-page TIFF frames, to take out one by one.

Everything happens on your computer: no file is uploaded anywhere.

## Installation

### Compatibility

Checked with `packaging/deb/test-clean-install.sh` in clean containers:

| System | Installation | Result |
|---|---|---|
| Debian 13 (trixie) | `.deb` package | install, full test suite on the installed package, upgrade, removal without leftovers |
| Ubuntu 26.04 LTS | `.deb` package | same as above |
| Ubuntu 24.04 LTS | `packaging/install-user.sh` | conversions and the wheel work (with ImageMagick 6 too). The `.deb` cannot be installed because 24.04 has no PySide6 in its repositories |
| Flatpak | `flatpak install` from the project's repository | conversions, wheel and Dolphin integration checked on KDE Plasma 6 (Debian 13); no LibreOffice |
| Windows 10/11 | `pip install` from source | experimental: engine, command line, window and wheel work and are tested on every push. The Explorer context menu and an installer are still missing |

On every push GitHub Actions runs the whole suite on **Debian 13** (with all the
engines, LibreOffice included) and on **Windows** (FFmpeg, ImageMagick, Pandoc,
Ghostscript, Poppler).

### Flatpak (any Linux distribution)

```sh
flatpak install --user https://pietrolama.github.io/anyfile/io.github.pietrolama.anyfile.flatpakref
```

Or open [pietrolama.github.io/anyfile](https://pietrolama.github.io/anyfile/) and click
*Install with Discover*. Updates arrive through Discover or `flatpak update`; the KDE runtime
comes from Flathub. Every engine is bundled except LibreOffice, so Office documents are
not converted in the Flatpak. After installing, press **Integrate with Dolphin** in the
window to add the right-click entry. The repository is signed with the key
`1B20 5824 C619 DE44 2766 270B 0C2D 414D 72C1 2491`, and it is built and published by
`.github/workflows/flatpak.yml` on every release.

### .deb package (Debian 13, Ubuntu 26.04 and later)

Download it from the [releases](https://github.com/pietrolama/anyfile/releases), then:

```sh
sudo apt install ./anyfile_0.5.0_all.deb
```

The package is about 40 KB and uses the system's Python and PySide6. Dependencies are
split like this:

| Kind | Packages | What they unlock |
|---|---|---|
| required | python3, python3-pyside6.*, file | the application |
| recommended (installed by apt) | ffmpeg, imagemagick, poppler-utils, ghostscript, qpdf, tesseract-ocr, libnotify-bin | images, audio, video, PDF, compression, PDF tools, text recognition, notifications |
| suggested | libreoffice-writer/calc/impress, pandoc, texlive-xetex, qt6-translations-l10n | Office documents, Markdown/EPUB, PDF from Markdown, translated Qt dialogs |

Removal: `sudo apt remove anyfile`. The package is built with `packaging/deb/build.sh`;
`packaging/deb/test-clean-install.sh [image]` tests it in a clean container.

### Development install, without root

```sh
git clone https://github.com/pietrolama/anyfile.git && cd anyfile
packaging/install-user.sh
```

It creates a virtualenv in `~/.local/share/anyfile/venv` pointing at the sources
(changes take effect immediately), the command `~/.local/bin/anyfile`, the menu entry
and the Dolphin action in your home folder. To remove everything:
`packaging/install-user.sh --uninstall`. Do not use it together with the `.deb`
package, or Dolphin would show two entries; the script detects this and stops.

### Windows (experimental)

You need Python 3.10+ and the engines you want, for example with winget:

```powershell
winget install Gyan.FFmpeg
winget install ImageMagick.ImageMagick
winget install JohnMacFarlane.Pandoc
winget install ArtifexSoftware.GhostScript
```

Then:

```powershell
git clone https://github.com/pietrolama/anyfile.git
cd anyfile
pip install .
anyfile engines
```

ANYFILE finds the engines on the PATH or in their standard install folders: nothing to
configure. The window opens with `anyfile`, the wheel with `anyfile --radial FILE`.

All the engines are optional: ANYFILE uses the ones it finds and tells you what to
install to unlock the other conversions (`anyfile engines`).

## The radial menu

In Dolphin: right-click one or more files → **Convert with ANYFILE**.

- A wheel appears **under the pointer** (on Wayland too), with one slice for each
  possible target, coloured and grouped by category: image, audio, video, document, PDF…
- **Click a slice** to convert: the progress shows in the centre, then “✓ Done”, and
  the wheel closes by itself. The new file is next to the original.
- **Click the centre** to open the full window with the files already loaded.
- **Esc**, a click outside or a right-click close the wheel. During a long conversion,
  Esc lets it continue in the background and a notification reports the outcome;
  a click on the centre cancels it instead.
- From the keyboard: arrows to choose, Enter to confirm, 1-2-3 for the quality.

### Compress

The first slice, at the top, makes the file **smaller in the same format**: JPEG and
WebP photos, lossy audio and video, PDF (with Ghostscript). The result is
`name-compressed.ext`; the original is never touched. If the compressed version is not
smaller it is discarded and the wheel shows “Already compact”. PNG, WAV, FLAC and
documents do not get this slice: there is nothing to gain in the same format.

### Tools

The **Tools** slice, at the top next to Compress, turns the wheel into the tools wheel:
edits that keep the format. The outer ring holds each tool's option, and a plain click
uses the usual one (•). The centre, Esc or Tab go back to the formats.

| Files | Tools (options) |
|---|---|
| Images | Resize (75, 50, 25%), Rotate (right, 180°, left), Mirror (horizontal, vertical), Black & white, Remove metadata, Recognize text (searchable PDF) |
| Video | Remove audio (copied, no re-encoding), Resize, Rotate, First frame (PNG) |
| Audio | Normalize volume (EBU R128, −16 LUFS, same sample rate), Mono |
| PDF | Merge (PDFs and images, in the order of the files), Split pages, Rotate, Page numbers (centre, right), Watermark (DRAFT, CONFIDENTIAL, COPY), Black & white, Repair, Protect (password to open, password to edit), Unlock, Recognize text (installed languages), Organize pages |

PDF edits work on the pages, so text, links and bookmarks stay as they are; Rotate, Page
numbers, Watermark, Repair, Protect and Unlock use qpdf, Black & white uses Ghostscript.

**Protected PDFs.** Protect encrypts with AES-256: “to open” asks for the password to
read the file, “to edit” lets anyone read and print it but not change it or copy its
text. Every operation works on a PDF that needs a password too: ANYFILE asks for it
before starting, decrypts a temporary copy and never stores the password (not even in
the history). On the command line it is typed in the terminal, or given with
`--password-file FILE`; it is never an argument, which would end up in the shell history.

**Organize pages** opens a window with the pages as thumbnails: drag them into a new
order, rotate, duplicate or remove them (Ctrl+L, Ctrl+R, Ctrl+←/→, Ctrl+D, Del), then
**Save** writes `name-organized.pdf`; **Save selected pages** extracts just those. Also
`anyfile --pages FILE.pdf`, or with the command line `anyfile edit -t organize --option
"3,1,2+90" FILE.pdf` (page 3, page 1, page 2 turned right).

**Recognize text** (OCR, with Tesseract) reads scans and photos and adds the text
underneath, invisible: the pages look exactly the same, but the text can be searched and
copied. Only pages without text are read. The outer ring offers the installed languages
(`sudo apt install tesseract-ocr-ita`, `-deu`, `-fra`...); the Flatpak includes English,
Italian, German, French, Spanish and Portuguese.

The result is a new file next to the original: `photo-resized.jpg`, `clip-silent.mp4`.
Animated GIFs keep every frame. With several files the wheel offers every tool that
applies to at least one of them, grouped by kind of file.

### Quality

Lossy formats have three presets, with parameters suited to each format:

| Preset | Photos (JPEG/WebP) | Audio (MP3, Opus…) | Video (H.264/VP9) | GIF |
|---|---|---|---|---|
| Maximum quality | quality 95 | ~245 kbit/s (MP3) | CRF 18 | 15 fps, 960 px |
| Balanced (default) | 85 / 80 | ~190 kbit/s | CRF 23 / 32 | 12 fps, 640 px |
| Smallest file | 70 / 60, no metadata | ~115 kbit/s | CRF 28 / 40, at most 720p | 8 fps, 400 px |

A click on the slice uses the default quality, which you choose in the full window.
**Moving outwards** from the slice reveals a ring with the three qualities; it stays
locked to the slice even when you move diagonally over the neighbouring ones.
“Compress” has two qualities only: at the maximum the file would grow. Lossless
formats show no ring.

### Chained conversions

When a format cannot be reached directly, ANYFILE goes through an intermediate format
and says so on the slice (“via PDF”):

| From | To | Via |
|---|---|---|
| DOCX, XLSX, PPTX, ODT, CSV… | PNG / JPG, one image per page | PDF |
| DOC, RTF, TXT | Markdown, HTML, EPUB, LaTeX | DOCX |
| EPUB, HTML | PDF, RTF | DOCX |
| PDF | DOCX, ODT, RTF (text only) | plain text |

Rules: at most one intermediate step, and only when there is no direct conversion.
The intermediate format is never lossy, so nothing is compressed twice. Paths that
would give an empty file are excluded: an image does not become text without OCR. The
losses of each step add up and are declared. Every intermediate file is checked, and
an error tells which step it happened in.

### Several files at once

With a mixed selection the wheel shows everything that can be done, putting first the
targets valid for more files. A slice that applies to only part of the selection
shows how many files it covers (e.g. “PDF 6/9”) and converts only those. “Compress”
is a single slice: it compresses each file in its own format.

## STRATUM: look inside a file

ANYFILE answers “how do I transform this file?”; STRATUM answers “what is inside it?”.
For supported files, the wheel has a **STRATUM** slice next to Tools. It opens an exploded
view in the same place, showing the components the file contains:

- **Videos** (MKV, MP4, WebM, MOV, AVI): video, audio, subtitles and cover tracks with language,
  codec, channels and flags. Extracted as-is or converted on the fly (audio to MP3/M4A/Opus/FLAC/WAV,
  subtitles to SRT/ASS/VTT).
- **Audio files** (MP3, FLAC, M4A, OGG, OPUS): embedded cover art (ID3 APIC, FLAC picture blocks,
  M4A covr) and synchronized lyrics/subtitles.
- **PDF documents**: embedded raster images and attached files extracted cleanly without opening an editor.
- **ZIP archives**: individual archive members with path traversal and zip bomb security guards.
- **Multi-frame / Multi-page images** (GIF animations, multi-page TIFF): individual frames or pages.

- **Click a component** to select it, then **click the centre** to extract the selection.
- **The outer ring** of an item (e.g. an audio track) allows converting it during extraction.
- **Esc**, or the centre with nothing selected, goes back to the wheel.
- From the keyboard: arrows, Space to select, 1-9 for a format, Enter to extract.

Each extracted file is validated. The original is never touched, and every extraction ends up in the history.

## History

Every conversion made with the wheel, the window or the command line ends up in the
same history. Open it from the full window (**History**, Ctrl+H), from the application
menu (right-click the icon → *Conversion history*) or with `anyfile --history`.

- Each operation shows when, the file, what was done and the result. “What” means, for
  example, “Compress JPEG · Small” or “Excel XLSX → PNG · via PDF”. The result is the
  size before and after with the saving, or the reason for an error, or “already
  compact”.
- **Repeat** runs it again with the same settings: format, quality, folder, overwrite.
  On failed conversions it becomes **Retry**, handy after fixing the problem, for
  example by installing a missing engine.
- **Repeat on other files…** applies the same procedure to new files.
- There are also search by name, an “Errors only” filter, *Show result* and *Remove*.
  *Clear history* deletes the entries, not the converted files.
- The last 1000 operations are kept in `~/.local/share/anyfile/history.sqlite`, on
  your computer only. Recording can be turned off from the window.

If the history is not available, for example because the database is damaged,
conversions still work.

## The full window

`anyfile [FILE...]`, the application menu, or the centre of the wheel. It offers:

- dropping files on the window;
- a format or a tool per file, or one for all with “For all files”: the tools of the
  wheel are at the end of each menu (files set to Merge become one PDF, in list order);
- destination folder and default quality, both remembered;
- overwriting only on request: otherwise the new file becomes `name (1).ext`;
- a queue with progress and cancellation;
- readable errors, with the technical details in the tooltip;
- the engine status, with the command to install the missing ones.

## Command line

```sh
anyfile info document.docx                    # detected format and possible targets
anyfile convert *.wav -t mp3 -o ~/Music        # conversion, several files too
anyfile convert video.mov -t mp4 -q small      # quality: max | balanced | small
anyfile convert photo.jpg -t jpg               # same format = compress
anyfile edit -t resize --option 25 *.jpg       # tools: resize, rotate, mute, split...
anyfile edit -t ocr --option ita scan.pdf      # recognize text (Italian)
anyfile edit -t protect contract.pdf          # asks for the new password
anyfile engines                                # installed and missing engines
anyfile history [-n 20] [--failed]             # history (--clear to delete it)
anyfile repeat 42 43                           # repeat history entries 42 and 43
anyfile explode film.mkv                       # STRATUM: the tracks inside a video
anyfile explode film.mkv -x 1 3:srt            # extract track 1 as it is, track 3 as SRT
anyfile --radial FILE...                       # open the wheel
```

## Languages

ANYFILE speaks **English** and **Italian** and follows the system language; numbers
follow it too (“926.8 KB” / “926,8 KB”). To force a language: `LANGUAGE=en anyfile`.

Translations are standard gettext files in `src/anyfile/locale/`, read directly at
runtime. To add a language:

```sh
sudo apt install gettext
scripts/i18n.sh new de          # creates src/anyfile/locale/de.po
# translate the msgstr entries, then:
scripts/i18n.sh                 # updates every .po file and checks it
```

A test makes sure every string in the code is translated in every `.po` file.

## Engines

| Engine | Used for |
|---|---|
| FFmpeg | audio ↔ audio, video ↔ video, audio extraction, video → GIF, compression |
| ImageMagick | PNG, JPEG, WebP, GIF, BMP, TIFF, ICO (reading AVIF/HEIC), images → PDF, compression |
| Poppler | PDF → text, PDF → PNG/JPEG (one image per page) |
| LibreOffice | DOCX/DOC/ODT/RTF/TXT, XLSX/XLS/ODS/CSV, PPTX/PPT/ODP to each other and → PDF |
| Pandoc | Markdown, HTML, EPUB, RST, LaTeX ↔ DOCX/ODT; → PDF when LaTeX is available |
| Ghostscript | PDF compression |

Capabilities are detected at start-up: FFmpeg encoders, ImageMagick coders, LaTeX. A
missing engine hides its conversions, and the app says what to install.

## Safety and reliability

- Engines are run with separate arguments, never through a shell.
- The engine reads a link with a neutral name (`input.png`): spaces, brackets or
  leading dashes in the file name never reach the command line.
- The format is recognized from the content, not the extension: a PNG named `.jpg` is
  treated as PNG.
- The output is prepared in a temporary folder and moved atomically. The source file
  is never replaced.
- The result is checked in its content (format signature, text, audio/video tracks),
  not only by the engine's exit code.
- LibreOffice uses a dedicated profile, so it works even when it is already open. In that
  profile document macros never run and links to other files are never updated.
- Each engine is told the format found in the content, so a crafted file cannot pass for
  something else. ImageMagick gets the input coder (`PNG:`, `JPEG:`…) and a private policy
  that refuses external programs, `@file` lists and the coders that read other files or
  URLs (MVG, MSL, SVG, TEXT, PostScript…), with limits on memory and image size. FFmpeg
  gets the demuxer, so a video cannot act as a playlist that pulls in other files, and
  opens local files only.
- Pandoc keeps only images inside the document's folder: remote images and paths that
  leave the folder are dropped, so a document can neither embed another file of yours nor
  reach the network. LaTeX (Markdown → PDF) cannot read files outside the folder or run
  programs.
- Ghostscript runs with `-dSAFER`.
- `tests/test_security.py` keeps these defences checked with crafted files.

ANYFILE is **not a sandbox**. The engines run with your permissions: a file crafted to
exploit a vulnerability in FFmpeg, ImageMagick, LibreOffice or Ghostscript could act
like any program you start. With files from untrusted sources, keep the engines up to
date. The Flatpak runs everything inside its sandbox, which still reaches your home folder
and removable drives; isolating each engine on its own (bubblewrap) is a possible next step.

## Architecture

```
src/anyfile/
  core/detector.py      detection: content signature → MIME → extension
  core/formats.py       format catalogue
  core/registry.py      conversion graph of the installed engines, chained paths
  core/planner.py       choice of the path for a file and a target
  core/executor.py      step-by-step execution, temporary files, safe placement
  core/validation.py    checks on the produced files
  core/jobs.py          job queue with progress and cancellation
  core/history.py       SQLite history shared by wheel, window and command line
  core/system.py        everything that depends on the operating system (Linux / Windows)
  stratum/              STRATUM: what a file contains (models/component.py), tracks of a video
  engines/              FFmpeg, ImageMagick, Poppler, LibreOffice + Pandoc, Ghostscript
  ui/radial.py          radial menu (ui/radial_geometry.py: geometry without Qt)
  ui/stratum_view.py    STRATUM's exploded view
  ui/main_window.py     full window
  ui/history_window.py  history window
  i18n.py, locale/      translations
  cli.py, app.py        entry points
packaging/              .desktop files, Dolphin action, install scripts, .deb
scripts/                test file generator, checklist, translation tools
tests/                  automated tests
```

Adding a format or an engine means declaring its conversions in `engines/`. The wheel,
the window, the command line and the chained paths use them with no other change.

## Development and testing

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

There are more than 250 automated tests. They generate small sample files with the
engines themselves and check real conversions, cancellation, name conflicts, presets,
chains, the history, translations and the behaviour of the wheel (with offscreen Qt).
A test is skipped when the engine it needs is not installed.

For manual testing:

```sh
python3 scripts/make_test_files.py     # creates manual-tests/ with one file per case
```

Then open `manual-tests/` in Dolphin and follow `00-CHECKLIST.md`: the action and the
expected result for each case, including the wheel, quality, Compress, chains, history,
languages and edge cases.

## Status

A prototype in active development, used daily on Debian 13 with KDE Plasma 6.3
(Wayland). PDF compression with Ghostscript is verified on real PDFs on Debian 13 and
Ubuntu 26.04, in clean containers.

Next steps: on Windows, the Explorer context menu and an installer with the engines
included; on Linux, Flatpak and isolation of the engines for untrusted files.

## How ANYFILE is made

Most of ANYFILE's code, tests, packaging and documentation were written by AI coding
assistants (mainly Claude Code), following my design and decisions; the commits written
with Claude say so in a `Co-Authored-By` line. I decide what goes in, review the changes
and try them on my own desktop: KDE Plasma 6 on Wayland, with Dolphin.

Nothing ships without automatic checks: 157 automated tests, which also run real
conversions with the real engines, run on Debian 13 and Windows on every push. The
`.deb` is installed, tested, upgraded and removed in a clean container before every
release. What only a real screen can show, such as where the wheel opens or the Dolphin
menu, is checked by hand with `manual-tests/00-CHECKLIST.md`.

Bug reports and reviews of the code are welcome, especially from people who know
Qt, Flatpak or the conversion engines well.

## License

ANYFILE is free software, released under the [GNU General Public License](LICENSE),
version 3 or (at your option) any later version (GPL-3.0-or-later). You can use,
study, modify and redistribute it; whoever distributes a modified version must make
its source available under the same license. ANYFILE comes with no warranty.

The conversion engines (FFmpeg, ImageMagick, Poppler, LibreOffice, Pandoc,
Ghostscript) are independent programs with their own licenses, run as external
processes.
