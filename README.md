# quick_transcribe

Offline prepis nahrávok (m4a, mp3, wav, mp4 …) do textu s prehľadávateľným archívom.
Prepis robí model Whisper (`faster-whisper`) priamo na tvojom počítači. Nahrávky ani texty sa nikam neposielajú.

Verzia 1.0.0 · Windows a Linux · Python 3.10+

## Inštalácia

```bash
pip install faster-whisper "av==16.0.1"
python make_shortcut.py          # voliteľne: ikona na ploche
```

`av` musí byť verzia 16.x, novšia nefunguje s `faster-whisper`.
Pri prvom prepise sa stiahne model (small ≈ 0,5 GB). Potom môže aplikácia bežať úplne offline.

## Spustenie

```bash
python quick_transcribe.py                       # otvorí aplikáciu na http://127.0.0.1:8774
python quick_transcribe.py nahravka.m4a          # otvorí aplikáciu a súbor hneď prepíše
python quick_transcribe.py transcribe nahravka.m4a --txt   # prepis v konzole, bez prehliadača
python quick_transcribe.py backup [PRIECINOK]    # záloha databázy a nahrávok
python quick_transcribe.py info                  # dátový priečinok, nastavenia, počet nahrávok
```

## Ako sa s aplikáciou pracuje

1. **Pridaj nahrávku:** tlačidlom **Add recordings…** alebo ju potiahni kamkoľvek na stránku. Súbory sa prepisujú jeden po druhom, priebeh vidíš vo fronte vľavo dole.
2. **Sleduj prepis:** text pribúda naživo. Hotový prepis zostane v archíve.
3. **Over a oprav:** klik na **čas** prehrá nahrávku od tohto miesta. Klik na **text** ho upraví (Enter uloží, Esc zruší). Pôvodné znenie sa zachová; upravený riadok má oranžovú bodku.
4. **Oprav mená naraz:** **Replace…** nahradí slovo v celom prepise. Pojmy a mená, ktoré sa opakujú, pridaj do **Glossary** v nastaveniach; model ich potom rozpozná lepšie.
5. **Hľadaj:** pole **Search all transcripts** (Ctrl+F) hľadá vo všetkých prepisoch. Klik na výsledok otvorí nahrávku na danom mieste.
6. **Použi výsledok:** **Copy** (do schránky), **Export** (TXT, Markdown, SRT), prípadne **Transcribe again…** iným modelom.
7. **Zálohuj:** **Backup** uloží databázu a nahrávky do priečinka nastaveného v **Settings**.
8. **Ukonči:** tlačidlo **Quit**.

Klávesy mimo textu: medzerník = prehrať / pauza, ←/→ = 5 s späť / dopredu.

## Kde sú dáta

`~/.quick_transcribe/` (zmena cez `data_dir` v `quick_transcribe.json`):
`transcripts.db` (SQLite), `audio/` (kópie nahrávok v kvalite reči, ≈ 10 MB za hodinu), `settings.json`, `quick_transcribe.log`.
Pôvodné súbory aplikácia nikdy nemení.

## Dokumentácia

- [Manuál](docs/MANUAL.md): inštalácia, obrazovka, nastavenia, dáta, záloha, bezpečnosť
- [Riešenie problémov](docs/TROUBLESHOOTING.md)

## Testy

```bash
python -m unittest discover -s quick_transcribe/tests -v
```

Testy nepotrebujú stiahnutý model.

## Štruktúra

```
QUICK_TRANSCRIBE/
├── quick_transcribe.py / .pyw    spúšťač (s konzolou / bez nej)
├── quick_transcribe.json         port, dátový priečinok
├── make_shortcut.py              ikona na ploche / v menu
├── quick_transcribe/             program: server, engine, db, static/ (stránka), tests/
└── docs/                         MANUAL.md, TROUBLESHOOTING.md
```

Autor: MEL
