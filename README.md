# ANYFILE

Convertitore di file locale per Linux (KDE Plasma su Debian/Ubuntu), con integrazione
nel menu contestuale di Dolphin. Si sceglie il risultato, non il motore: ANYFILE
rileva il formato, mostra solo le conversioni realmente eseguibili con i programmi
installati, le esegue in sicurezza e verifica il file prodotto.

## Installazione (utente, senza root)

```sh
sudo apt install ffmpeg imagemagick pandoc libreoffice poppler-utils   # anche solo alcuni
packaging/install-user.sh
```

Lo script crea un virtualenv in `~/.local/share/anyfile/venv`, il comando
`~/.local/bin/anyfile`, la voce nel menu applicazioni e il service menu di Dolphin
(`~/.local/share/kio/servicemenus/anyfile.desktop`). Per rimuovere tutto:
`packaging/install-user.sh --uninstall`.

## Uso

- **Dolphin**: tasto destro su uno o più file → *Converti con ANYFILE*. Si apre il
  **menu radiale** sotto il puntatore: una fetta per ogni formato raggiungibile,
  raggruppate per categoria. Clic su una fetta per convertire; clic al centro per la
  finestra completa; Esc per chiudere (durante una conversione lunga, Esc la lascia
  proseguire in background con una notifica finale). Funziona anche con frecce e Invio.
  Con più file selezionati la ruota mostra tutto ciò che si può fare: le fette che
  valgono solo per una parte dei file indicano quanti (es. «6/9») e convertono solo quelli.
- **Comprimi**: la prima fetta della ruota rende il file più leggero restando nello
  stesso formato (JPEG, WebP, audio e video con perdita, PDF con Ghostscript) e salva
  `nome-compresso.ext` accanto all'originale. Se il risultato non è più leggero viene
  scartato e la ruota mostra «Già compatto». Da terminale: `anyfile convert foto.jpg -t jpg`.
- **Conversioni concatenate**: se un formato non è raggiungibile direttamente, ANYFILE
  passa da un formato intermedio, per esempio XLSX → PDF → PNG (una immagine per pagina),
  DOC → DOCX → Markdown, EPUB → DOCX → PDF. La ruota e la finestra indicano «via PDF» e
  sommano le perdite dichiarate di ogni passaggio. Regole: al massimo un intermedio, mai
  un intermedio con perdita (niente doppia compressione), nessun percorso che darebbe un
  file vuoto (un'immagine non diventa testo senza OCR); ogni file intermedio viene
  verificato e un errore indica il passaggio in cui è avvenuto.
- **Qualità**: per i formati con perdita (JPEG, WebP, MP3, Ogg, Opus, AAC, video, GIF)
  ci sono tre preset: *Massima qualità*, *Bilanciata* (predefinita) e *File più leggero*
  (che riduce anche i video a 720p e toglie i metadati dalle foto). Nella ruota, il clic
  sulla fetta usa la qualità predefinita; scorrendo verso l'esterno compare l'anello dei
  preset (o si premono 1-2-3). Per PNG, WAV, FLAC e documenti i preset non compaiono:
  non cambierebbero nulla. La qualità predefinita si sceglie nella finestra completa.
- **Menu radiale da terminale**: `anyfile --radial FILE...`
- **Interfaccia**: `anyfile [FILE...]`, oppure trascina i file nella finestra.
- **Terminale**:
  ```sh
  anyfile info foto.heic              # formato rilevato e destinazioni possibili
  anyfile convert *.wav -t mp3 -o ~/Musica
  anyfile convert video.mov -t mp4 -q leggera   # massima | bilanciata | leggera
  anyfile engines                     # motori installati e comando per i mancanti
  ```

## Motori

| Motore      | Conversioni                                                            |
| ----------- | ---------------------------------------------------------------------- |
| FFmpeg      | audio ↔ audio, video ↔ video, estrazione audio, video → GIF            |
| ImageMagick | PNG, JPEG, WebP, GIF, BMP, TIFF, ICO (lettura AVIF/HEIC), immagini → PDF |
| Poppler     | PDF → testo, PDF → PNG/JPEG (una immagine per pagina)                  |
| Ghostscript | compressione dei PDF (facoltativo: `sudo apt install ghostscript`)     |
| LibreOffice | DOCX/DOC/ODT/RTF/TXT, XLSX/XLS/ODS/CSV, PPTX/PPT/ODP ↔ e → PDF          |
| Pandoc      | Markdown, HTML, EPUB, RST, LaTeX ↔ DOCX/ODT; → PDF se c'è LaTeX        |

Le capacità vengono rilevate all'avvio (encoder di FFmpeg, coder di ImageMagick,
presenza di LaTeX): un motore assente nasconde le sue conversioni e l'app spiega
cosa installare.

## Architettura

```
src/anyfile/
  core/detector.py    firma del contenuto → MIME → estensione
  core/formats.py     catalogo dei formati
  core/registry.py    grafo delle conversioni offerte dai motori installati
  core/planner.py     scelta del percorso: diretto o con un passaggio intermedio
  core/executor.py    esecuzione isolata, file temporanei, collocamento sicuro
  core/validation.py  verifica dell'output (firma, testo, tracce audio/video)
  core/jobs.py        coda dei lavori con avanzamento e annullamento
  engines/            FFmpeg, ImageMagick, LibreOffice + Pandoc, Poppler
  ui/                 interfaccia PySide6 (finestra e menu radiale)
  cli.py, app.py      punti di ingresso
packaging/            .desktop, service menu Dolphin, script di installazione
```

Scelte di sicurezza:

- i motori sono invocati con argomenti separati, mai tramite shell;
- il motore legge un collegamento con nome neutro (`input.png`), quindi spazi,
  parentesi o trattini iniziali nel nome del file non arrivano alla riga di comando;
- l'output si prepara in una cartella temporanea nella destinazione e viene spostato
  in modo atomico; senza consenso non si sovrascrive nulla (`nome (1).ext`) e il file
  sorgente non viene mai sostituito;
- LibreOffice usa un profilo dedicato, così funziona anche con LibreOffice già aperto;
- il risultato è verificato nel contenuto, non solo con il codice di uscita.

## Sviluppo

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest            # i test generano piccoli file di esempio con i motori
```

## Prossimi passi

Cronologia e ripetizione delle conversioni, pacchetto `.deb`/Flatpak.
