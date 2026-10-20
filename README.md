# ANYFILE

Convertitore di file locale per Linux, pensato per KDE Plasma su Debian/Ubuntu.
Tasto destro su un file in Dolphin, e una ruota sotto il puntatore mostra cosa puoi
farne: convertirlo, comprimerlo, scegliere la qualità. Si sceglie il risultato, non
il programma: ANYFILE rileva il formato, offre solo le conversioni che i motori
installati sanno davvero eseguire, le esegue in sicurezza e verifica il file prodotto.

Tutto avviene sul computer: nessun file viene caricato in rete.

## Installazione

### Compatibilità

Verificata con `packaging/deb/test-clean-install.sh` in container puliti:

| Sistema | Installazione | Risultato |
|---|---|---|
| Debian 13 (trixie) | pacchetto `.deb` | installazione, 111 test sul pacchetto, aggiornamento e rimozione senza residui |
| Ubuntu 26.04 LTS | pacchetto `.deb` | come sopra |
| Ubuntu 24.04 LTS | `packaging/install-user.sh` | conversioni e ruota funzionanti (anche con ImageMagick 6). Il `.deb` non si installa perché la 24.04 non ha PySide6 nei repository |

### Pacchetto .deb (Debian 13, Ubuntu 26.04 e successive)

```sh
sudo apt install ./anyfile_0.2.0_all.deb
```

Il pacchetto pesa circa 40 KB e usa Python e PySide6 del sistema. Le dipendenze sono
divise così:

| Tipo | Pacchetti | Cosa sbloccano |
|---|---|---|
| obbligatorie | python3, python3-pyside6.*, file | l'applicazione |
| consigliate (installate da apt) | ffmpeg, imagemagick, poppler-utils, ghostscript, libnotify-bin | immagini, audio, video, PDF, compressione, notifiche |
| suggerite | libreoffice-writer/calc/impress, pandoc, texlive-xetex | documenti Office, Markdown/EPUB, PDF da Markdown |

Rimozione: `sudo apt remove anyfile`. Il pacchetto si costruisce con
`packaging/deb/build.sh`. `packaging/deb/test-clean-install.sh [immagine]` lo prova in
un container pulito: installazione, suite di test completa sul pacchetto installato,
aggiornamento e rimozione.

### Installazione per sviluppo, senza root

```sh
git clone https://github.com/pietrolama/anyfile.git && cd anyfile
packaging/install-user.sh
```

Crea un virtualenv in `~/.local/share/anyfile/venv` che punta ai sorgenti (le modifiche
sono subito attive), il comando `~/.local/bin/anyfile`, la voce nel menu e l'azione di
Dolphin nella home. Per rimuovere tutto: `packaging/install-user.sh --uninstall`. Non va
usata insieme al pacchetto `.deb`: Dolphin mostrerebbe due voci. Lo script lo rileva e
si ferma.

I motori sono tutti facoltativi: ANYFILE usa quelli presenti e spiega cosa installare
per sbloccare le altre conversioni (`anyfile engines`).

## Il menu radiale

In Dolphin: tasto destro su uno o più file → **Converti con ANYFILE**.

- Compare una ruota **sotto il puntatore** (anche su Wayland), con una fetta per ogni
  destinazione possibile, colorata e raggruppata per categoria: immagine, audio, video,
  documento, PDF…
- **Clic su una fetta** per convertire: al centro si vede l'avanzamento, poi «✓ Fatto»
  e la ruota si chiude da sola. Il nuovo file è accanto all'originale.
- **Clic al centro** apre la finestra completa con i file già caricati.
- **Esc**, clic fuori o tasto destro chiudono la ruota. Durante una conversione lunga,
  Esc la lascia proseguire in background: una notifica ne darà l'esito. Il clic al
  centro, invece, la annulla.
- Da tastiera: frecce per scegliere, Invio per confermare, 1-2-3 per la qualità.

### Comprimi

La prima fetta, in alto, rende il file **più leggero restando nello stesso formato**:
foto JPEG e WebP, audio e video con perdita, PDF (con Ghostscript). Il risultato è
`nome-compresso.ext`; l'originale non viene mai toccato. Se la versione compressa non
è più leggera viene scartata e la ruota mostra «Già compatto». PNG, WAV, FLAC e
documenti non hanno questa fetta: nello stesso formato non c'è nulla da guadagnare.

### Qualità

Per i formati con perdita ci sono tre preset, con parametri adatti a ciascun formato:

| Preset | Foto (JPEG/WebP) | Audio (MP3, Opus…) | Video (H.264/VP9) | GIF |
|---|---|---|---|---|
| Massima qualità | qualità 95 | ~245 kbit/s (MP3) | CRF 18 | 15 fps, 960 px |
| Bilanciata (predefinita) | 85 / 80 | ~190 kbit/s | CRF 23 / 32 | 12 fps, 640 px |
| File più leggero | 70 / 60, senza metadati | ~115 kbit/s | CRF 28 / 40, max 720p | 8 fps, 400 px |

Il clic sulla fetta usa la qualità predefinita, che si sceglie nella finestra completa.
**Scorrendo verso l'esterno** dalla fetta compare un anello con le tre qualità. L'anello
resta agganciato alla fetta anche passando in diagonale sopra quelle vicine. Per
«Comprimi» le qualità sono due: alla massima il file crescerebbe. Per i formati senza
perdita l'anello non compare.

### Conversioni concatenate

Se un formato non è raggiungibile direttamente, ANYFILE passa da un formato intermedio
e lo indica sulla fetta («via PDF»):

| Da | A | Via |
|---|---|---|
| DOCX, XLSX, PPTX, ODT, CSV… | PNG / JPG, una immagine per pagina | PDF |
| DOC, RTF, TXT | Markdown, HTML, EPUB, LaTeX | DOCX |
| EPUB, HTML | PDF, RTF | DOCX |
| PDF | DOCX, ODT, RTF (solo il testo) | testo |

Regole: al massimo un intermedio, e solo se manca la conversione diretta. L'intermedio
non è mai un formato con perdita, per non comprimere due volte. Sono esclusi i percorsi
che darebbero un file vuoto: un'immagine non diventa testo senza OCR. Le perdite di
ogni passaggio vengono sommate e dichiarate. Ogni file intermedio viene verificato, e
un errore indica il passaggio in cui è avvenuto.

### Più file insieme

Con una selezione mista la ruota mostra tutto ciò che si può fare, mettendo prima le
destinazioni valide per più file. Una fetta che vale solo per una parte della
selezione indica quanti file copre (es. «PDF 6/9») e converte solo quelli. «Comprimi»
è una sola fetta: comprime ogni file nel proprio formato.

## La finestra completa

`anyfile [FILE...]`, il menu delle applicazioni, o il centro della ruota. Le funzioni:

- trascinamento dei file nella finestra;
- formato scelto file per file, oppure per tutti con «Converti tutti in»;
- cartella di destinazione e qualità predefinita, entrambe ricordate;
- sovrascrittura solo se richiesta: altrimenti il nuovo file diventa `nome (1).ext`;
- coda con avanzamento e annullamento;
- errori leggibili, con i dettagli tecnici nel tooltip;
- stato dei motori, con il comando per installare quelli mancanti.

## Terminale

```sh
anyfile info documento.docx                   # formato rilevato e destinazioni possibili
anyfile convert *.wav -t mp3 -o ~/Musica       # conversione, anche di più file
anyfile convert video.mov -t mp4 -q leggera    # qualità: massima | bilanciata | leggera
anyfile convert foto.jpg -t jpg                # stesso formato = comprimi
anyfile engines                                # motori installati e mancanti
anyfile --radial FILE...                       # apre la ruota
```

## Motori

| Motore | Usato per |
|---|---|
| FFmpeg | audio ↔ audio, video ↔ video, estrazione dell'audio, video → GIF, compressione |
| ImageMagick | PNG, JPEG, WebP, GIF, BMP, TIFF, ICO (lettura AVIF/HEIC), immagini → PDF, compressione |
| Poppler | PDF → testo, PDF → PNG/JPEG (una immagine per pagina) |
| LibreOffice | DOCX/DOC/ODT/RTF/TXT, XLSX/XLS/ODS/CSV, PPTX/PPT/ODP tra loro e → PDF |
| Pandoc | Markdown, HTML, EPUB, RST, LaTeX ↔ DOCX/ODT; → PDF se c'è LaTeX |
| Ghostscript | compressione dei PDF |

Le capacità vengono rilevate all'avvio: encoder di FFmpeg, coder di ImageMagick,
presenza di LaTeX. Un motore assente nasconde le sue conversioni, e l'app spiega cosa
installare.

## Sicurezza e affidabilità

- I motori sono invocati con argomenti separati, mai tramite shell.
- Il motore legge un collegamento con nome neutro (`input.png`): spazi, parentesi o
  trattini iniziali nel nome del file non arrivano mai alla riga di comando.
- Il formato si riconosce dal contenuto, non dall'estensione: un PNG chiamato `.jpg`
  viene trattato come PNG.
- L'output si prepara in una cartella temporanea e viene spostato in modo atomico. Il
  file sorgente non viene mai sostituito.
- Il risultato è verificato nel contenuto (firma del formato, testo, tracce audio/video),
  non solo con il codice di uscita del motore.
- LibreOffice usa un profilo dedicato, quindi funziona anche se è già aperto.
- Ghostscript è eseguito con `-dSAFER`.

ANYFILE **non è una sandbox**. I motori girano con i permessi dell'utente: un file
costruito apposta per sfruttare una vulnerabilità di FFmpeg, ImageMagick, LibreOffice o
Ghostscript potrebbe agire come un qualsiasi programma avviato dall'utente. Con file di
provenienza non attendibile conviene tenere aggiornati i motori. Un isolamento vero
(bubblewrap, Flatpak) è un possibile sviluppo futuro.

## Architettura

```
src/anyfile/
  core/detector.py      rilevamento: firma del contenuto → MIME → estensione
  core/formats.py       catalogo dei formati
  core/registry.py      grafo delle conversioni dei motori installati, percorsi concatenati
  core/planner.py       scelta del percorso per un file e una destinazione
  core/executor.py      esecuzione passo per passo, file temporanei, collocamento sicuro
  core/validation.py    verifica dei file prodotti
  core/jobs.py          coda dei lavori con avanzamento e annullamento
  engines/              FFmpeg, ImageMagick, Poppler, LibreOffice + Pandoc, Ghostscript
  ui/radial.py          menu radiale (ui/radial_geometry.py: geometria senza Qt)
  ui/main_window.py     finestra completa
  cli.py, app.py        punti di ingresso
packaging/              .desktop, azione di Dolphin, script di installazione
scripts/                generatore dei file di prova e checklist
tests/                  test automatici
```

Aggiungere un formato o un motore significa dichiararne le conversioni in `engines/`.
Ruota, finestra, terminale e percorsi concatenati le usano senza altre modifiche.

## Sviluppo e prove

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

I test automatici sono più di 120. Generano piccoli file di esempio con i motori stessi e
controllano le conversioni reali. Coprono anche annullamento, conflitti di nome,
preset, catene e il comportamento della ruota (con Qt offscreen). Un test viene
saltato se il motore che serve non è installato.

Per le prove a mano:

```sh
python3 scripts/genera_prove.py        # crea prove-manuali/ con un file per ogni caso
```

Poi si apre `prove-manuali/` in Dolphin e si segue `00-CHECKLIST.md`: azione e
risultato atteso per ogni caso, inclusi ruota, qualità, Comprimi, catene e casi limite.

## Stato

Prototipo in sviluppo attivo, usato su Debian 13 con KDE Plasma 6.3 (Wayland).
La compressione dei PDF con Ghostscript è verificata su PDF reali in Debian 13 e
Ubuntu 26.04, nei container puliti.

Prossimi passi: cronologia con ripetizione delle conversioni, pacchetto `.deb`,
poi Flatpak.

## Licenza

ANYFILE è software libero, distribuito secondo i termini della
[GNU General Public License](LICENSE), versione 3 o (a tua scelta) qualsiasi versione
successiva (GPL-3.0-or-later). Puoi usarlo, studiarlo, modificarlo e ridistribuirlo;
chi distribuisce una versione modificata deve renderne disponibile il codice con la
stessa licenza. ANYFILE è fornito senza alcuna garanzia.

I motori di conversione (FFmpeg, ImageMagick, Poppler, LibreOffice, Pandoc,
Ghostscript) sono programmi indipendenti, con le rispettive licenze, avviati come
processi esterni.
