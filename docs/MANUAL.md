# quick_transcribe – manuál

Verzia 1.0.0 · offline prepis nahrávok (m4a, mp3, wav, mp4 …) do textu s prehľadávateľným archívom.
Prepis robí model Whisper (knižnica `faster-whisper`) priamo na tvojom počítači. Nahrávky ani texty sa nikam neposielajú.

## 1. Inštalácia

Celý nástroj je v jednom priečinku `QUICK_TRANSCRIBE/`:

| Súbor / priečinok | Čo to je |
|---|---|
| `quick_transcribe.py` | spúšťač |
| `quick_transcribe.pyw` | ten istý spúšťač bez konzoly (ikona na ploche vo Windows) |
| `quick_transcribe.json` | konfigurácia spustenia (port, dátový priečinok) |
| `quick_transcribe.ico`, `quick_transcribe.png` | ikona (Windows / Linux) |
| `make_shortcut.py` | vytvorí odkaz na ploche (Windows) alebo spúšťač v menu a na ploche (Linux) |
| `quick_transcribe/` | program (Python moduly, `static/` so stránkou, `tests/`) |
| `docs/` | tento manuál a riešenie problémov |

Závislosti (raz, v aktivovanom prostredí):

```bash
pip install faster-whisper "av==16.0.1"
```

`av` musí byť verzia 16.x. Novšia (17+) nefunguje s `faster-whisper` (chyba `metadata_errors`). Spúšťač na to upozorní.

**Ikona na ploche:** spusti `make_shortcut.py` tým Pythonom, ktorým má nástroj bežať, napr.

```bash
~/Dev/Env/Personal/Scripts/python.exe make_shortcut.py      # Git Bash, Windows
python3 make_shortcut.py                                     # Linux, v aktivovanom prostredí
```

Na Windowse vznikne `quick_transcribe.lnk` na ploche (cez `pythonw.exe`, bez konzoly). Na Linuxe `quick_transcribe.desktop` v menu aplikácií a na ploche. Po presune priečinka skript spusti znova.

## 2. Spustenie

| Príkaz | Čo robí |
|---|---|
| `python quick_transcribe.py` | otvorí aplikáciu v prehliadači na `http://127.0.0.1:8774` |
| `python quick_transcribe.py SUBOR [SUBOR …]` | otvorí aplikáciu a súbory hneď zaradí na prepis (aj celý priečinok) |
| `python quick_transcribe.py transcribe SUBOR [--model medium --lang en --txt]` | prepis v konzole, bez prehliadača; `--txt` zapíše `SUBOR.txt` vedľa nahrávky |
| `python quick_transcribe.py backup [PRIECINOK]` | záloha databázy a archivovaných nahrávok |
| `python quick_transcribe.py info` | dátový priečinok, nastavenia, počet nahrávok |

Voľby: `--port 8775`, `--host 0.0.0.0`, `--no-browser`. Ak aplikácia už beží, druhé spustenie nový proces nezakladá: odovzdá súbory bežiacej aplikácii a otvorí stránku.
Ukončenie: tlačidlo **Quit** alebo Ctrl+C v konzole.

**Prvé spustenie prepisu stiahne model** z Hugging Face (small ≈ 0,5 GB, medium ≈ 1,5 GB). Sťahuje sa len model, smerom k tebe. Potom môžeš v nastaveniach zapnúť **Offline only** a aplikácia sa na internet nepripojí vôbec.

## 3. Obrazovka

**Ľavý panel**
- **Add recordings…** alebo potiahnutie súborov kamkoľvek na stránku: súbory sa skopírujú do aplikácie a zaradia na prepis.
- **Search all transcripts:** fulltextové hľadanie vo všetkých prepisoch. Hľadá aj začiatky slov (`demonstr` nájde *demonstrators*) a ignoruje diakritiku. Klik na výsledok otvorí nahrávku na danom mieste. Skratka Ctrl+F.
- **Recordings:** zoznam nahrávok, najnovšie hore. Počet upravených riadkov je v popise.
- **Queue:** fronta prepisov s priebehom. Prepisuje sa jedna nahrávka naraz, ostatné čakajú. **Cancel** zastaví prepis; hotová časť zostane uložená. **Clear** skryje dokončené úlohy.

**Hlavná časť**
- **Názov** nahrávky sa dá prepísať priamo v hornom poli.
- **Prehrávač:** prehráva archivovanú kópiu nahrávky. **Follow playback** posúva prepis s prehrávaním a zvýrazní aktuálny riadok. Rýchlosť 0,75–2×.
- **Prepis:** riadky s časom.
  - **Klik na čas** = prehranie od tohto miesta.
  - **Klik na text** = úprava. Enter alebo odchod z riadku uloží, Esc zruší. Pôvodný text zostáva v databáze; upravený riadok má oranžovú bodku (nabehni na ňu myšou a uvidíš originál). Ak riadok vrátiš na pôvodné znenie, bodka zmizne.
  - Kým prepis beží, nové riadky pribúdajú naživo.
- **Export:** TXT s časmi, TXT čistý text, Markdown (s hlavičkou: dátum, dĺžka, model), SRT titulky.
- **Copy:** prepis s časmi do schránky, napr. na vloženie do chatu na zápis zo schôdzky.
- **Replace…:** nahradí slovo v celom prepise tejto nahrávky, napr. „Mermec“ → „MERMEC“. Označený text sa predvyplní.
- **Transcribe again…:** nový prepis tej istej nahrávky iným modelom alebo jazykom. Aktuálny prepis aj tvoje úpravy sa nahradia.
- **Delete:** zmaže prepis a archivovanú kópiu. Pôvodný súbor sa nemení nikdy.
- **Backup**, **Settings**, **Quit** vpravo hore.

Klávesy mimo textu: medzerník = prehrať / pauza, šípky ←/→ = 5 s späť / dopredu.

## 4. Nastavenia

| Položka | Význam |
|---|---|
| Model | `tiny`/`base` rýchle a hrubé · `small` dobrý základ · `medium` lepšie mená a prízvuky, asi 3× pomalší · `large-v3` najlepší, na CPU pomalý |
| Language | jazyk nahrávky; **Detect** zistí jazyk sám (pomalšie, pri zmiešanom jazyku menej spoľahlivé) |
| Device | CPU alebo NVIDIA GPU (CUDA). GPU potrebuje knižnice CUDA/cuDNN, inak zostaň na CPU |
| Offline only | nastaví `HF_HUB_OFFLINE=1`; model musí byť už stiahnutý |
| Glossary | pojmy a mená, jeden na riadok. Model ich dostane ako nápovedu (`initial_prompt`) a lepšie ich rozpozná. Drž to krátke, do ~50 pojmov |
| Audio | **Keep a compact copy:** archív uloží kópiu v kvalite reči (Opus, mono, 16 kHz, 24 kb/s ≈ 10 MB za hodinu). Potrebná na prehrávanie a Transcribe again |
| TXT file | pri súboroch otvorených z disku (príkazový riadok, `/api/open`) zapíše `.txt` aj vedľa zdroja |
| Backup folder | kam ide záloha, napr. firemný OneDrive |

Rýchlosť na bežnom notebooku (CPU, model small): asi 5–8× rýchlejšie, než je dĺžka nahrávky. Dvojhodinová schôdzka ≈ 15–25 minút. Pred prepisom sa vytvára archivovaná kópia, to trvá rádovo desiatky sekúnd.

## 5. Kde sú dáta

Dátový priečinok je predvolene `~/.quick_transcribe` (Windows: `C:\Users\<meno>\.quick_transcribe`). Zmeníš ho v `quick_transcribe.json` (`"data_dir"`).

| Súbor | Obsah |
|---|---|
| `transcripts.db` | SQLite databáza: tabuľky `recordings`, `segments` (aj pôvodný text a príznak úpravy), fulltextový index `segments_fts` |
| `audio/00001.opus …` | archivované kópie nahrávok (číslo = id nahrávky) |
| `inbox/` | dočasné kópie nahrávaných súborov; po prepise sa mažú |
| `settings.json` | nastavenia zmenené v aplikácii |
| `quick_transcribe.log` | chyby (hlavne pri spustení cez ikonu, keď nie je konzola) |

**Duplicity:** ten istý súbor (rovnaký obsah, SHA-1) sa druhýkrát neprepisuje; úloha skončí stavom `duplicate` s odkazom na existujúcu nahrávku. Na nový prepis použi **Transcribe again**, alebo v konzole `transcribe --force`.

**Záloha:** tlačidlo **Backup** alebo `quick_transcribe.py backup` vytvorí v zálohovom priečinku `quick_transcribe_backup/transcripts_RRRRMMDD_HHMMSS.db` (posledných 20 sa drží) a dokopíruje nové súbory z `audio/`. Obnova: zastav aplikáciu a skopíruj vybraný `.db` ako `transcripts.db` do dátového priečinka.

Databázu môžu čítať aj iné nástroje (napr. organizér projektov). Nahrávka má stále `id`, segmenty sa naň viažu cez `recording_id`.

## 6. Testy

```bash
python -m unittest discover -s quick_transcribe/tests -v
```

Testy nepotrebujú model (používajú falošný). Overujú databázu, vyhľadávanie, úpravy, export, archiváciu zvuku, frontu (zrušenie, chyba, duplicita, nový prepis) a HTTP rozhranie.

## 7. Bezpečnosť a súkromie

- Server počúva len na `127.0.0.1`, teda len na tomto počítači. `--host 0.0.0.0` použi len vtedy, ak vieš, prečo.
- Požiadavky, ktoré niečo menia, musia mať hlavičku `X-QT`, ktorú posiela len stránka aplikácie. Iná webová stránka v prehliadači ich tak nevie vyvolať.
- Na internet sa aplikácia pripája len pri sťahovaní modelu. S **Offline only** vôbec.
- Nahrávky schôdzok môžu obsahovať dôverné informácie projektu. Dátový a zálohový priečinok drž na firemnom úložisku.
