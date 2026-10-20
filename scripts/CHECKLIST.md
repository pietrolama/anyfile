# Checklist delle prove manuali

Apri questa cartella in Dolphin. Tasto destro sul file → **Converti con ANYFILE**
apre il **menu radiale** sotto il puntatore: clic su un formato per convertire.
Per le prove indicate «in ANYFILE» clicca il **centro** del menu: si apre la finestra completa.
Per ripartire da zero: `python3 scripts/genera_prove.py --pulisci`.

## Menu radiale

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| R1 | `01-foto.png` | Tasto destro → Converti con ANYFILE | Il menu compare **sotto il puntatore**, con le fette raggruppate per categoria |
| R2 | `01-foto.png` | Passa sulle fette | La fetta si evidenzia; al centro il formato, sotto la nota (es. «Le aree trasparenti diventano bianche») |
| R3 | `01-foto.png` | Clic su WEBP | Avanzamento al centro, «✓ Fatto», il menu si chiude da solo; il file è accanto all'originale |
| R4 | `01-foto.png` | Frecce ←/→ e Invio | Stessa scelta da tastiera |
| R5 | Qualsiasi | Esc, clic fuori, tasto destro | Il menu si chiude senza fare nulla |
| R6 | `09-video-lungo.mp4` | Clic su WEBM, poi **Esc** | Il menu sparisce, la conversione continua; a fine lavoro arriva una notifica |
| R7 | `09-video-lungo.mp4` | Clic su WEBM, poi clic al **centro** («Annulla») | Conversione annullata, nessun file parziale |
| R8 | `01-foto.png` + `06-animata.gif` + `07-tono.wav` | Selezionali insieme → menu | Fette immagine «2/3» e audio «1/3»: ognuna converte solo i file compatibili |
| R9 | `01-foto.png` + `02-trasparente.png` + `17-archivio.zip` | Selezionali insieme → menu | Solo formati immagine; «1 file non riconosciuto sarà ignorato» |
| R10 | `08-clip-breve.mp4` | Menu | 12 fette: Video, Immagine (GIF), Audio |
| R11 | `18-danneggiato.png` | Menu → JPG | «✕ Errore» al centro e messaggio sotto; il centro apre la finestra completa, dove riconvertendo si leggono i dettagli nel tooltip |
| R12 | Vicino al bordo dello schermo | Menu | Il menu resta interamente visibile |

## Qualità

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| Q1 | `01-foto.png` | Menu → passa su JPG | Al centro «Bilanciata»; sotto «Qualità 85» e l'invito a scorrere verso l'esterno |
| Q2 | `01-foto.png` | Su JPG scorri verso l'esterno, anche in diagonale | Compare l'anello Massima · Bilanciata · Leggera; resta agganciato a JPG |
| Q3 | `01-foto.png` | JPG → Massima, poi JPG → Leggera | `01-foto.jpg` ≈ 640 KB, `01-foto (1).jpg` ≈ 90 KB |
| Q4 | `01-foto.png` | Passa su PNG o TIFF | Nessun anello di qualità |
| Q5 | `01-foto.png` | Su JPG premi 3 | Converte subito con «File più leggero» |
| Q6 | `09-video-lungo.mp4` | WEBM → Leggera | Video a 720p, molto più piccolo (verifica con le proprietà in Dolphin) |
| Q7 | Finestra | Qualità: «File più leggero», chiudi e riapri | La scelta è ricordata, e la ruota la usa come predefinita (segnata con •) |

## Comprimi

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| C1 | `20-foto-pesante.jpg` | Menu | Prima fetta in alto: **COMPRIMI**; anello con sole «Bilanciata» e «Leggera» |
| C2 | `20-foto-pesante.jpg` | Clic su COMPRIMI | Nasce `20-foto-pesante-compresso.jpg` (≈ 240 KB invece di ≈ 950 KB); l'originale resta |
| C3 | `20-foto-pesante.jpg` | COMPRIMI → Leggera | ≈ 140 KB, senza metadati |
| C4 | `21-gia-compressa.jpg` | Clic su COMPRIMI | Al centro «＝ Già compatto», sotto le dimensioni a confronto; nessun file creato |
| C5 | `09-video-lungo.mp4` | COMPRIMI → Leggera | `09-video-lungo-compresso.mp4` a 720p |
| C6 | `15-tre-pagine.pdf` | Menu | Senza Ghostscript niente fetta COMPRIMI; dopo `sudo apt install ghostscript` compare |
| C7 | `01-foto.png` | Menu | Niente COMPRIMI: un PNG non si riduce senza cambiare formato (usa JPG o WEBP) |
| C8 | `20-foto-pesante.jpg` + `09-video-lungo.mp4` + `01-foto.png` | Selezionali → menu | Una sola fetta COMPRIMI «2/3»: ogni file resta nel suo formato |
| C9 | Finestra | Riga di una JPEG | Prima voce: «Comprimi (stesso formato)» |

## Selezioni multiple

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| M1 | Dieci file diversi | Selezionali → menu | Fette con conteggi (es. «PDF 6/9»), prima le destinazioni valide per più file |
| M2 | Come M1 | Clic su PDF | Converte solo i 6 compatibili; gli altri restano intatti |

## Immagini

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| 1 | `01-foto.png` | → JPEG, WebP, ICO, PDF | File validi accanto all'originale |
| 2 | `02-trasparente.png` | → JPEG | Sfondo **bianco**, non nero |
| 3 | `03-png-travestito.jpg` | Apri in ANYFILE | Formato «PNG ⚠»; il tooltip spiega che l'estensione non corrisponde |
| 3b | `03-png-travestito.jpg` | → JPEG con «Sovrascrivi» attivo | Crea `03-png-travestito (1).jpg`: l'originale non viene toccato |
| 4 | `04-conflitto.png` | → JPEG | Crea `04-conflitto (1).jpg`, il `04-conflitto.jpg` esistente resta intatto |
| 4b | `04-conflitto.png` | → JPEG con «Sovrascrivi» | Sostituisce `04-conflitto.jpg` |
| 5 | `05-nome strano [1] -x.png` | → WebP | Funziona nonostante spazi, parentesi e trattino |
| 6 | `06-animata.gif` | → WebP / → PNG / → MP4 | WebP animata; PNG con solo il primo fotogramma (vedi tooltip); MP4 video |

## Audio e video

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| 7 | `07-tono.wav` | → MP3, FLAC, Opus | File riproducibili |
| 8 | `08-clip-breve.mp4` | → GIF, → WebM, → MP3 | GIF animata; WebM; solo audio |
| 9 | `09-video-lungo.mp4` | → WebM, poi **Annulla** a metà | Barra di avanzamento; stato «Annullato»; nessun file parziale (né `.anyfile-*`) nella cartella |

## Documenti

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| 10 | `10-documento.docx` | → PDF, → ODT, → Markdown | PDF/ODT con tabella; Markdown con il testo |
| 10b | `10-documento.docx` | → PDF **con LibreOffice aperto** | Funziona lo stesso (profilo separato) |
| 11 | `11-foglio.xlsx` | → ODS, → CSV, → PDF | CSV leggibile con gli accenti |
| 12 | `12-presentazione.pptx` | → PDF, → ODP | Due slide |
| 13 | `13-nota.md` | → DOCX, → HTML, → PDF | HTML apribile nel browser |
| 14 | `14-dati.csv` | → XLSX | Tabella con 3 righe |
| 15 | `15-tre-pagine.pdf` | → PNG | Cartella `15-tre-pagine-pagine/` con 3 immagini |
| 15b | `15-tre-pagine.pdf` | → Testo | Testo delle tre pagine |
| 16 | `16-scansione.pdf` | → Testo | Errore leggibile: «non contiene testo estraibile… serve l'OCR» |

## Casi limite

| # | File | Azione | Risultato atteso |
|---|------|--------|------------------|
| 17 | `17-archivio.zip` | Apri in ANYFILE | Riga grigia «Formato non riconosciuto», menu disattivato |
| 18 | `18-danneggiato.png` | → JPEG | Stato «✗ ImageMagick non è riuscito…»; tooltip con i dettagli; le altre conversioni della coda proseguono |
| 19 | `19-vuoto.txt` | Apri in ANYFILE | «Il file è vuoto» |
| 20 | Tutti i file insieme | Seleziona tutto → ANYFILE → «Converti tutti in: PDF» | Il PDF viene impostato solo dove è possibile; gli altri restano su «Scegli formato…» |
| 21 | Una cartella | Trascinala nella finestra | Messaggio in basso: le cartelle non sono supportate |
| 22 | Qualsiasi | «Salva in:» una cartella diversa | I risultati finiscono lì; «Mostra risultati» apre Dolphin sul file |
| 23 | `09-video-lungo.mp4` | Avvia, poi riduci la finestra a icona | Notifica di sistema a fine conversione |
| 24 | `09-video-lungo.mp4` | Avvia e chiudi la finestra | Chiede se annullare le conversioni in corso |
