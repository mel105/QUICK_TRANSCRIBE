# quick_transcribe – riešenie problémov

| Príznak | Príčina | Riešenie |
|---|---|---|
| `quick_transcribe cannot start: this Python has no faster_whisper, av` | spúšťaš iným Pythonom, než kde sú balíky | aktivuj prostredie (`source ~/Dev/Env/Personal/Scripts/activate`) alebo `pip install faster-whisper "av==16.0.1"`; hláška ukáže cestu k použitému Pythonu |
| `PyAV 19.x does not work with faster-whisper` alebo `unexpected keyword argument 'metadata_errors'` | `pip` nainštaloval najnovšie PyAV | `pip install "av==16.0.1"` |
| Úloha skončí chybou s `LocalEntryNotFound` / „model is not downloaded yet“ | je zapnuté **Offline only** a model ešte nie je stiahnutý | vypni Offline only, spusti jeden prepis s internetom, potom ho znova zapni |
| Sťahovanie modelu zlyhá na firemnej sieti | proxy alebo blokovaný `huggingface.co` | stiahni model raz doma (stačí jeden krátky prepis), potom funguje offline; prípadne požiadaj IT o povolenie `huggingface.co` |
| `cannot start the server on 127.0.0.1:8774` | port je obsadený | `--port 8775` alebo zmeň `server.port` v `quick_transcribe.json` |
| Stránka píše „quick_transcribe does not answer“ | proces skončil (Quit, zatvorená konzola) | spusti ho znova a obnov stránku |
| Ikona na ploche nič neotvorí | chyba pri štarte nie je vidieť (pythonw nemá konzolu) | spusti raz `python quick_transcribe.py` v konzole a prečítaj hlášku; pozri aj `quick_transcribe.log` v dátovom priečinku |
| Úloha má stav `duplicate` | ten istý súbor už je v archíve | otvor existujúcu nahrávku (**Open**) a použi **Transcribe again** |
| Prehrávač chýba, časy sa nedajú kliknúť | nahrávka nemá archivovanú kópiu (vypnuté **Keep a compact copy**) | zapni ho v Settings; pre staré nahrávky ich prepíš znova z pôvodného súboru (`transcribe --force`) |
| `Neither the source file nor an archived copy is available` pri Transcribe again | pôvodný súbor sa presunul a kópia nie je | pridaj súbor znova; prepíše sa ako nová nahrávka |
| Prepis má zlé mená a skratky | model ich nepozná | doplň ich do **Glossary**; opravy v hotovom prepise rob cez **Replace…**; pri slabom zvuku skús model `medium` |
| Prepis „vymýšľa“ opakujúce sa vety v tichu | známa vlastnosť Whisperu pri dlhom tichu | nechaj zapnutý VAD filter (predvolené); tieto riadky zmaž alebo prepíš |
| Prepis je veľmi pomalý | veľký model na CPU | `small` je na CPU rozumný kompromis; `large-v3` len s GPU |
| Device CUDA hlási chybu knižníc (`cublas`, `cudnn`) | chýbajú CUDA/cuDNN knižnice | prepni Device na CPU |
| Riadok sa nedá uložiť prázdny | prázdny riadok by rozbil časovú os | napíš aspoň `…` alebo riadok nechaj |
| Hľadanie nenájde časť slova v strede | fulltext hľadá začiatky slov | hľadaj od začiatku slova (`demonstr`, nie `onstrat`) |
| `info` hlási `LIKE (slower)` | Python má SQLite bez FTS5 | funguje, len pomalšie hľadanie pri veľkom archíve |
| Po havárii zostane nahrávka v stave `error` s „Interrupted“ | aplikácia sa zavrela počas prepisu | **Transcribe again** |
