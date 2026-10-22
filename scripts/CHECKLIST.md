# Manual test checklist

Open this folder in Dolphin. Right-click a file → **Convert with ANYFILE** opens the
**radial menu** under the pointer: click a format to convert. For the tests marked
“in ANYFILE”, click the **centre** of the menu: the full window opens.
To start again from scratch: `python3 scripts/make_test_files.py --clean`.

The interface follows the system language. To check the English one on an Italian
desktop: `LANGUAGE=en anyfile --radial FILE`.

## Radial menu

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| R1 | `01-photo.png` | Right-click → Convert with ANYFILE | The menu appears **under the pointer**, slices grouped by category |
| R2 | `01-photo.png` | Hover the slices | The slice lights up; the format in the centre, the note below (e.g. “Transparent areas become white”) |
| R3 | `01-photo.png` | Click WEBP | Progress in the centre, “✓ Done”, the menu closes by itself; the file is next to the original |
| R4 | `01-photo.png` | Arrows ←/→ and Enter | Same choice from the keyboard |
| R5 | Any | Esc, click outside, right-click | The menu closes without doing anything |
| R6 | `09-long-video.mp4` | Click WEBM, then **Esc** | The menu disappears, the conversion continues; a notification arrives at the end |
| R7 | `09-long-video.mp4` | Click WEBM, then click the **centre** (“Cancel”) | Conversion cancelled, no partial file |
| R8 | `01-photo.png` + `06-animated.gif` + `07-tone.wav` | Select them together → menu | Image slices “2/3” and audio “1/3”: each converts only the compatible files |
| R9 | `01-photo.png` + `02-transparent.png` + `17-archive.zip` | Select them together → menu | Image formats only; “1 unrecognized file will be ignored” |
| R10 | `08-short-clip.mp4` | Menu | 12 slices: Video, Image (GIF), Audio |
| R11 | `18-damaged.png` | Menu → JPG | “✕ Error” in the centre and the message below; the centre opens the full window, where converting again shows the details in the tooltip |
| R12 | Near the edge of the screen | Menu | The menu stays fully visible |

## Quality

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| Q1 | `01-photo.png` | Menu → hover JPG | “Balanced” in the centre; below, “Quality 85” and the hint to move outwards |
| Q2 | `01-photo.png` | On JPG move outwards, diagonally too | The Maximum · Balanced · Small ring appears and stays locked to JPG |
| Q3 | `01-photo.png` | JPG → Maximum, then JPG → Small | `01-photo.jpg` ≈ 640 KB, `01-photo (1).jpg` ≈ 90 KB |
| Q4 | `01-photo.png` | Hover PNG or TIFF | No quality ring |
| Q5 | `01-photo.png` | On JPG press 3 | Converts right away with “Smallest file” |
| Q6 | `09-long-video.mp4` | WEBM → Small | 720p video, much smaller (check the properties in Dolphin) |
| Q7 | Window | Quality: “Smallest file”, close and reopen | The choice is remembered, and the menu uses it as default (marked with •) |

## Compress

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| C1 | `20-heavy-photo.jpg` | Menu | First slice at the top: **COMPRESS**; ring with only “Balanced” and “Small” |
| C2 | `20-heavy-photo.jpg` | Click COMPRESS | `20-heavy-photo-compressed.jpg` appears (≈ 240 KB instead of ≈ 950 KB); the original stays |
| C3 | `20-heavy-photo.jpg` | COMPRESS → Small | ≈ 140 KB, without metadata |
| C4 | `21-already-compressed.jpg` | Click COMPRESS | “＝ Already compact” in the centre, the sizes compared below; no file created |
| C5 | `09-long-video.mp4` | COMPRESS → Small | `09-long-video-compressed.mp4` at 720p |
| C6 | `15-three-pages.pdf` | Menu | Without Ghostscript no COMPRESS slice; after `sudo apt install ghostscript` it appears |
| C7 | `01-photo.png` | Menu | No COMPRESS: a PNG cannot shrink without changing format (use JPG or WEBP) |
| C8 | `20-heavy-photo.jpg` + `09-long-video.mp4` + `01-photo.png` | Select them → menu | A single COMPRESS slice “2/3”: each file stays in its own format |
| C9 | Window | Row of a JPEG | First entry: “Compress (same format)” |

## Chained conversions

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| K1 | `11-sheet.xlsx` | Menu | PNG, JPG, TXT slices with “via PDF” |
| K2 | `11-sheet.xlsx` | → PNG | `11-sheet.png` with the table |
| K3 | `12-slides.pptx` | → PNG | Folder `12-slides-pages/` with one image per slide |
| K4 | `15-three-pages.pdf` | Hover DOCX | “via Plain text · Text only…”: it says the layout is lost |
| K5 | `10-document.docx` | Window, the row's menu | Chains show “· via PDF” next to the format |
| K6 | `08-short-clip.mp4` | Menu | No PNG/JPG slice: going through GIF would degrade twice |
| K7 | `01-photo.png` | Menu | No TXT/DOCX slice: an image contains no text without OCR |
| K8 | `anyfile info manual-tests/11-sheet.xlsx` | Terminal | Chains are shown with “(via pdf)” |

## History

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| H1 | Any | Convert something from the menu, then window → **History** (Ctrl+H) | The menu's conversions are there, with operation and result |
| H2 | `20-heavy-photo.jpg` | COMPRESS → Small, then open the history | “Compress JPEG · Small — 927 KB → 134 KB (−86%)” |
| H3 | `18-damaged.png` | → JPG, then select the row in the history | Result in red; the button says **Retry** |
| H4 | A successful row | **Repeat** | New entry at the top; the new file is `name (1).ext`, nothing overwritten |
| H5 | A successful row | **Repeat on other files…** and pick 2 files | Same operation and quality on the new files |
| H6 | An entry whose original you deleted | Repeat | Warning “no longer exist”; no new entry |
| H7 | ANYFILE icon in the menu | Right-click → *Conversion history* | The history opens directly |
| H8 | History window | Untick “Record new conversions”, convert a file | No new entry |
| H9 | Terminal | `anyfile history` and `anyfile repeat ID` | Same content as the window; repeating works |

## Language

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| L1 | Any | Open the menu and the window on an Italian desktop | Everything in Italian, numbers with a decimal comma (“926,8 KB”) |
| L2 | Any | `LANGUAGE=en anyfile` | Everything in English, numbers with a decimal point (“926.8 KB”) |
| L3 | Dolphin | Context menu on an English and an Italian desktop | “Convert with ANYFILE” / “Converti con ANYFILE” |

## Multiple selections

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| M1 | Ten different files | Select them → menu | Slices with counts (e.g. “PDF 6/9”), targets valid for more files first |
| M2 | As M1 | Click PDF | Converts only the 6 compatible files; the others stay untouched |

## Images

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| 1 | `01-photo.png` | → JPEG, WebP, ICO, PDF | Valid files next to the original |
| 2 | `02-transparent.png` | → JPEG | **White** background, not black |
| 3 | `03-png-named-jpg.jpg` | Open in ANYFILE | Format “PNG ⚠”; the tooltip explains that the extension does not match |
| 3b | `03-png-named-jpg.jpg` | → JPEG with “Overwrite” on | Creates `03-png-named-jpg (1).jpg`: the original is not touched |
| 4 | `04-conflict.png` | → JPEG | Creates `04-conflict (1).jpg`; the existing `04-conflict.jpg` stays intact |
| 4b | `04-conflict.png` | → JPEG with “Overwrite” | Replaces `04-conflict.jpg` |
| 5 | `05-odd name [1] -x.png` | → WebP | Works despite spaces, brackets and dash |
| 6 | `06-animated.gif` | → WebP / → PNG / → MP4 | Animated WebP; PNG with only the first frame (see tooltip); MP4 video |

## Audio and video

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| 7 | `07-tone.wav` | → MP3, FLAC, Opus | Playable files |
| 8 | `08-short-clip.mp4` | → GIF, → WebM, → MP3 | Animated GIF; WebM; audio only |
| 9 | `09-long-video.mp4` | → WebM, then **Cancel** halfway | Progress bar; status “Cancelled”; no partial file (nor `.anyfile-*`) in the folder |

## Documents

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| 10 | `10-document.docx` | → PDF, → ODT, → Markdown | PDF/ODT with the table; Markdown with the text |
| 10b | `10-document.docx` | → PDF **with LibreOffice open** | Works anyway (separate profile) |
| 11 | `11-sheet.xlsx` | → ODS, → CSV, → PDF | Readable CSV |
| 12 | `12-slides.pptx` | → PDF, → ODP | Two slides |
| 13 | `13-note.md` | → DOCX, → HTML, → PDF | HTML that opens in the browser |
| 14 | `14-data.csv` | → XLSX | Table with 3 rows |
| 15 | `15-three-pages.pdf` | → PNG | Folder `15-three-pages-pages/` with 3 images |
| 15b | `15-three-pages.pdf` | → Text | Text of the three pages |
| 16 | `16-scan.pdf` | → Text | Readable error: “contains no extractable text… use “Recognize text” among the tools first” |

## Edge cases

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| 17 | `17-archive.zip` | Open in ANYFILE | Grey row “Unrecognized format”, menu disabled |
| 18 | `18-damaged.png` | → JPEG | Status “✗ ImageMagick could not…”; tooltip with the details; the other conversions in the queue carry on |
| 19 | `19-empty.txt` | Open in ANYFILE | “The file is empty” |
| 20 | All files together | Select all → ANYFILE → “For all files: PDF” | PDF is set only where possible; the others stay on “Choose…” |
| 21 | A folder | Drop it on the window | Message at the bottom: folders are not supported |
| 22 | Any | “Save in:” a different folder | The results end up there; “Show results” opens Dolphin on the file |
| 23 | `09-long-video.mp4` | Start, then minimize the window | System notification at the end |
| 24 | `09-long-video.mp4` | Start and close the window | Asks whether to cancel the running conversions |

## Protected PDFs, text recognition, pages

Make a protected copy first: wheel on `15-three-pages.pdf` → Tools → Protect → “To open”.

| # | File | Action | Expected result |
|---|------|--------|-----------------|
| 25 | `15-three-pages.pdf` | Wheel → Tools → Protect | Password dialog **above the wheel**, with “Repeat”; OK only when both match; `…-protected.pdf` asks for the password in Okular |
| 26 | `…-protected.pdf` | Wheel → PNG | Password dialog above the wheel; a wrong one says “Wrong password, try again” and stays open; the right one converts |
| 27 | `…-protected.pdf` | Wheel → Tools | Unlock is there, Protect is not; Unlock gives a PDF that opens without a password |
| 28 | A real scan or photo of a page | Wheel → Tools → Recognize text | `…-searchable.pdf` looks the same; text can be selected and found with Ctrl+F in Okular |
| 29 | `15-three-pages.pdf` | Wheel → Tools → Organize pages | The wheel closes, the pages window opens in front with the thumbnails |
| 30 | Pages window | **Drag** a page to a new place with the mouse | The page moves there (not on top of another page); the summary says “new order” |
| 31 | Pages window | Rotate, Duplicate, Remove, Save | `…-organized.pdf` matches what the window showed; “Show result” opens Dolphin on it |
| 32 | Full window, two PDFs | Both rows on “Merge” → Convert | One `…-merged.pdf` with the files in list order; both rows show it |
