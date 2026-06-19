# Measurement Devices Communication Library

Standalone-Python-Projekt zur Ablösung des vorhandenen VBA-Add-ins für Messgerätekommunikation.

## Ziel

Das Projekt kommuniziert per VISA/SCPI mit Messgeräten, liest Messwerte, Screenshots, Waveforms oder S-Parameter aus und schreibt die Ergebnisse in eine Excel-Datei. Binärdaten wie Screenshots werden zusätzlich als Datei neben der Excel-Datei abgelegt und in Excel referenziert.

## Installation

1. Python 3.10 oder neuer installieren.
2. Eine VISA-Runtime installieren, falls USB/GPIB/TCPIP-Geräte darüber angebunden sind. Empfohlen ist die schlanke R&S VISA Runtime: [R&S VISA Downloadseite](https://www.rohde-schwarz.com/us/applications/rs-visa_56280-148812.html), Windows-Installer: [RS_VISA_Setup_Win_7_2_6.exe](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/dl_application/application_notes/1dc02___rs_v/RS_VISA_Setup_Win_7_2_6.exe). Alternativ funktionieren auch NI-VISA oder Keysight VISA.
3. Abhängigkeiten installieren:

```powershell
py -m pip install -e .
```

Hinweis für GPIB: Der GPIB-Controller-Treiber sollte zur verwendeten VISA-Installation passen. Bei einem NI-GPIB-Adapter ist NI-VISA häufig die robustere Wahl.

## EXE-Build

Für die Weitergabe an Kollegen kann eine Windows-EXE mit PyInstaller gebaut werden. Die VISA-Runtime muss trotzdem auf dem Zielrechner installiert sein; die EXE enthält nur das Python-Tool und dessen Python-Abhängigkeiten.

```powershell
scripts\build_exe.ps1
```

Das Skript installiert bei Bedarf `pyinstaller`, entfernt alte Build-Artefakte und erzeugt eine Onedir-Anwendung unter:

```text
dist\MeasurementDevicesCommunicationLibrary\MeasurementDevicesCommunicationLibrary.exe
```

Der Ordner `dist\MeasurementDevicesCommunicationLibrary` kann anschließend als ZIP weitergegeben werden. `README.md` und `config.example.ini` werden mit in den Ordner kopiert, falls sie vorhanden sind.

Für sauber benannte Verteilerordner kann das Paketier-Skript ausgeführt werden. Es baut standardmäßig zuerst die EXE neu und erzeugt danach beide Verteilerordner:

```powershell
scripts\package_release.ps1
```

Wenn `pyinstaller` bereits installiert ist, geht es schneller mit:

```powershell
scripts\package_release.ps1 -SkipInstall
```

Falls nur aus einem bereits vorhandenen `dist\MeasurementDevicesCommunicationLibrary` paketiert werden soll:

```powershell
scripts\package_release.ps1 -SkipExeBuild
```

Es erzeugt zwei Ordner unter `release\`:

```text
MeasurementDevicesCommunicationLibrary_EXE_Windows_<Datum>
MeasurementDevicesCommunicationLibrary_Python_Source_<Datum>
```

Der EXE-Ordner ist für Kollegen ohne Python gedacht. Der Python-Source-Ordner enthält Quellcode, Tests, Skripte, `pyproject.toml`, README und Beispielkonfiguration.

## Konfiguration

`config.example.ini` nach `config.ini` kopieren und Adresse/Ausgabedatei anpassen.

## Nutzung

```powershell
instrument-visa list
instrument-visa idn --config config.ini
instrument-visa value --config config.ini
instrument-visa scope-value --measurement Vpp --channel 1 --config config.ini
instrument-visa screenshot --config config.ini
instrument-visa waveform --channels 1,2 --point-mode RAW --config config.ini
instrument-visa sparameters --config config.ini
```

## Oberfläche

Die einfache Oberfläche kann direkt aus dem Projektordner gestartet werden:

```powershell
py -m instrument_visa.gui
```

Nach `py -m pip install -e .` steht zusätzlich dieser Befehl zur Verfügung:

```powershell
instrument-visa-gui
```

Zusätzlich stehen nach der Installation die neuen Aliasse zur Verfügung:

```powershell
measurement-devices
measurement-devices-gui
```

Die Oberfläche bietet Geräte-Suche, IDN-Test, DMM-Messwert, Scope-Messwert, getimtes Messen, Screenshot, Waveform-Export und S-Parameter-Export in eine auswählbare Excel-Datei. Nach `IDN testen` wird ein Geräteprofil erkannt und die passenden Bereiche werden aktiviert. Für Oszilloskope sollte `Scope Messwert` genutzt werden, da `DMM Messwert` den Multimeter-Befehl `:READ?` sendet. Beim Waveform-Export können `CH1` bis `CH4` beliebig kombiniert werden. Zusätzlich ist der Punktmodus `RAW`, `NORMAL` oder `MAXIMUM` auswählbar. Jede Waveform-Messung wird zur besseren Übersicht in ein eigenes Tabellenblatt geschrieben.

Beim getimten Messen kann eine DMM- oder Scope-Messreihe mit Intervall in Sekunden und Anzahl Messpunkte gestartet werden. Die Messpunkte werden auf feste Sollzeitpunkte geplant, damit die Messdauer das Intervall nicht dauerhaft verschiebt. Die Messreihe kann über `Stop` abgebrochen werden. Die Ergebnisse werden mit Index, Zeitstempel, verstrichener Zeit, Delta zum vorherigen Messpunkt, Abweichung vom Sollzeitpunkt, Messart, Kanal, Wert und Status in ein eigenes Tabellenblatt geschrieben. Zusätzlich enthält das Tabellenblatt eine Zusammenfassung mit Start-/Endzeit, Soll-Intervall, angeforderter und tatsächlicher Anzahl sowie OK- und Fehlerzähler.

Die GUI merkt sich zuletzt verwendete Einstellungen in `gui_settings.json`, darunter VISA-Adresse, bekannte Geräte, Excel-Datei, Scope-Messung, Timed-Measurement-Intervall, Timed-Measurement-Anzahl, Waveform-Kanäle, Waveform-Punktmodus und S-Parameter-Auswahl. Nach einer erfolgreichen IDN-Abfrage wird die VISA-Adresse zusammen mit IDN, Gerätetyp, Profil und unterstützten Funktionen gespeichert. Bekannte Geräte erscheinen beim nächsten Start direkt in der Geräte-Liste mit Typ, Hersteller, Modell und Adresse. Bei einer neuen Gerätesuche werden die gefundenen VISA-Adressen mit den bekannten Geräten zusammengeführt, sodass bereits erkannte Geräte sofort mit Typ angezeigt und die passenden Bedienbereiche aktiviert werden. Die Auswahl eines bekannten Geräts nutzt das gespeicherte Profil ohne automatische IDN-Abfrage; für eine erneute Erkennung kann `IDN testen` manuell gestartet werden. Die Buttons `Excel öffnen` und `Ordner öffnen` öffnen direkt die Ergebnisdatei bzw. den Ausgabeordner. Der Excel-Export ergänzt Zeitstempel, Metadaten und eigene Tabellenblätter für Waveform- und Messreihendaten. Waveform-Tabellenblätter bekommen automatisch ein Diagramm, wenn numerische Daten erkannt werden. PNG-Screenshots werden zusätzlich in ein eigenes Excel-Tabellenblatt eingebettet.

Alle GUI- und CLI-Aktionen werden dauerhaft in `logs/instrument_visa.log` protokolliert. Das Log enthält gestartete Aktionen, Exportpfade, erkannte Geräteprofile und vollständige Fehlerdetails.

## Aus dem VBA-Projekt übernommene Funktionen

- VISA-Initialisierung und `*IDN?`-Abfrage
- Geräteerkennung über IDN-String
- Screenshots für E740, E5071C, FSW, Keysight/Agilent DSO/MSO/MSOX, PXA/MXA/EXA/CXA, ZNB und Tektronix-Geräte
- Waveform-/Messwertausgabe für E740, 4395A, Keysight/Agilent 3000X/MSOX/6000/7000 und 344xx/L44xx
- S-Parameter-Dateien für E5071C und R&S ZNB
- Excel-Ausgabe per `openpyxl`

## Geräteunterstützung

Die folgenden Geräteprofile sind mit realen Geräten aus diesem Projekt getestet oder aus dem vorhandenen VBA-Projekt übernommen:

- Keysight/Agilent 344xx/L44xx, darunter 34461A und 34401A: DMM-Messwert und getimtes DMM-Messen über `:READ?`
- Keysight/Agilent InfiniiVision X-Series, darunter DSOX2024A und MSOX3054T: Scope-Messwert, getimtes Scope-Messen, Screenshot und Waveform-Export
- Keysight/Agilent E5071C: Screenshot und S-Parameter-Export
- Rohde & Schwarz ZNB: Screenshot und S-Parameter-Export
- Keysight/Agilent/HP E740 und HP/Agilent 4395A: Exportfunktionen aus dem VBA-Projekt

Die folgenden Geräteprofile sind als best-effort implementiert, aber noch nicht mit den konkreten Laborgeräten getestet. Die SCPI-Befehle wurden gegen öffentlich verfügbare Programmierhandbücher bzw. Hersteller-Manual-Seiten gegengeprüft, soweit zugänglich. Sie erscheinen nach `IDN testen` mit Gerätetyp und aktivierten Funktionen; Rückmeldungen aus Tests sollten im Log `logs/instrument_visa.log` geprüft werden:

- Keysight/Agilent InfiniiVision 6000, darunter MSO6034A/DSO6034A: Scope-Messwert, getimtes Scope-Messen, Screenshot und Waveform-Export mit 6000-Series-Programmer-SCPI (`:MEASure...`, `:WAVeform...`, `:DISPlay:DATA?`)
- Keysight/Agilent InfiniiVision 7000, darunter DSO7034B/MSO7034: Scope-Messwert, getimtes Scope-Messen, Screenshot und Waveform-Export mit 7000-Series-Programmer-SCPI (`:MEASure...`, `:WAVeform...`, `:DISPlay:DATA? PNG, SCREEN, COLOR`)
- HP/Agilent 54600/54620, darunter 54622D: Scope-Messwert, Screenshot und Waveform-Export mit 54620-Series-Programmer-SCPI. Screenshot nutzt BMP, da das 54622D-Manual bei `:DISPlay:DATA?` nur `TIFF | BMP` nennt.
- Keithley 2000: DMM-Messwert und getimtes DMM-Messen über `:READ?`, laut Keithley-Manual als `:ABORt`, `:INITiate`, `:FETCh?`-Sequenz beschrieben
- Tektronix TDS400, darunter TDS420A: Scope-Messwert, Screenshot und Waveform-Export mit TDS-Family-Programmer-SCPI (`MEASUrement:IMMed...`, `DATa:SOUrce`, `DATa:ENCdg ASCii`, `CURVe?`, `HARDCopy START`). Screenshot nutzt TIFF, da PNG im TDS400A-Manual nicht als sicher unterstütztes Hardcopy-Format aufgeführt ist.
- Tektronix TDS3000/MDO/MSO/DPO: Scope-Messwert und Waveform zusätzlich zu Screenshot best-effort aktiviert
- Rohde & Schwarz / Hameg HMS-X: Screenshot und Trace-Export mit HMS-X-SCPI-Programmer-Manual gegengeprüft (`HCOPy:FORMat BMP`, `HCOPy:DATA?`, `TRACe:DATA:FORMat CSV`, `TRACe:DATA?`). Screenshot nutzt BMP, da das Manual nur BMP für `HCOPy:FORMat` aufführt.
- Rohde & Schwarz RT-Series-Oszilloskope, falls IDN `RTB`, `RTA`, `RTM`, `RTE`, `RTO` oder `RTP` enthält: Scope-Messwert, Screenshot und Waveform mit RTB2000-Manual-SCPI (`MEASurement...`, `HCOPy:DATA?`, `CHANnel:DATA?`)
- Teledyne LeCroy WavePro/WaveRunner/SDA/Zi: Scope-Messwert, Screenshot und Waveform-Export mit X-Stream/WaveRunner-Remote-Control-SCPI (`PAVA?`, `SCREEN_DUMP`, `INSPECT? "SIMPLE"`)

PicoScope-Geräte wie PicoScope 2206BMSO oder 2406B sind bewusst nicht integriert, da sie typischerweise nicht per VISA/SCPI angesprochen werden, sondern über PicoSDK.

## Geräte-Testmatrix

Statuswerte:

- `getestet`: mit realem Gerät im aktuellen Python-Tool geprüft
- `VBA übernommen`: aus dem vorhandenen VBA-Projekt übernommen, im Python-Tool noch nicht neu mit realem Gerät bestätigt
- `commands from manual, untested`: SCPI-Kommandos aus Programmierhandbuch abgeleitet, aber noch nicht mit realem Laborgerät bestätigt
- `offen`: noch zu testen oder zu konkretisieren
- `nicht integriert`: bewusst nicht im VISA/SCPI-Tool umgesetzt

### Getestet

#### Keysight/Agilent 344xx/L44xx, 34461A, 34401A

    Profil-Key:        keysight_344_l44
    IDN-Erkennung:     344 oder L44
    Funktionen:        DMM/Messwert ja, getimtes DMM-Messen ja
    Nicht unterstützt: Scope-Messwert, Screenshot, Waveform/Trace, S-Parameter
    Status:            getestet
    Notizen:           34461A/34401A über :READ?; 34401A/HP/Agilent-Varianten fallen bewusst in dasselbe Profil

#### Keysight/Agilent InfiniiVision X-Series, DSOX2024A, MSOX3054T

    Profil-Key:        keysight_infinivision_x
    IDN-Erkennung:     DSOX oder MSOX
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            getestet
    Notizen:           Neue getimte Messung wurde mit Scope positiv getestet

### Aus VBA Übernommen

#### Keysight/Agilent E5071C

    Profil-Key:        keysight_e5071c
    IDN-Erkennung:     E5071C
    Funktionen:        Screenshot PNG, S-Parameter ja
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Waveform/Trace
    Status:            VBA übernommen
    Notizen:           Screenshot und Touchstone/S-Parameter aus bestehender Logik übernommen

#### Rohde & Schwarz ZNB

    Profil-Key:        rs_znb
    IDN-Erkennung:     ZNB
    Funktionen:        Screenshot PNG, S-Parameter ja
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Waveform/Trace
    Status:            VBA übernommen
    Notizen:           Screenshot und Touchstone/S-Parameter aus bestehender Logik übernommen

#### Keysight/Agilent/HP E740

    Profil-Key:        hp_e740
    IDN-Erkennung:     E740
    Funktionen:        Screenshot WMF, Trace CSV
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, S-Parameter
    Status:            VBA übernommen
    Notizen:           Spektrumanalysator-Export aus bestehender Logik übernommen

#### HP/Agilent 4395A

    Profil-Key:        hp_4395a
    IDN-Erkennung:     4395A
    Funktionen:        Waveform/Trace ja
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Screenshot, S-Parameter
    Status:            VBA übernommen
    Notizen:           Waveform-/Trace-Export aus bestehender Logik übernommen

### Commands From Manual, Untested

#### Keysight/Agilent InfiniiVision 6000, MSO6034A/DSO6034A

    Profil-Key:        keysight_infinivision_6000
    IDN-Erkennung:     MSO6 oder DSO6
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Noch mit Laborgerät testen

#### Keysight/Agilent InfiniiVision 7000, DSO7034B/MSO7034

    Profil-Key:        keysight_infinivision_7000
    IDN-Erkennung:     MSO7 oder DSO7
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Noch mit Laborgerät testen

#### HP/Agilent 54600/54620, 54622D

    Profil-Key:        agilent_54600
    IDN-Erkennung:     54622D oder 5462
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot BMP, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Screenshot bewusst BMP; noch mit Laborgerät testen

#### Keithley 2000

    Profil-Key:        keithley_2000
    IDN-Erkennung:     KEITHLEY und 2000
    Funktionen:        DMM/Messwert ja, getimtes DMM-Messen ja
    Nicht unterstützt: Scope-Messwert, Screenshot, Waveform/Trace, S-Parameter
    Status:            commands from manual, untested
    Notizen:           DMM über :READ?; noch mit Laborgerät testen

#### Tektronix TDS400, TDS420A

    Profil-Key:        tektronix_tds400
    IDN-Erkennung:     TEKTRONIX und TDS420 oder TDS4
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot TIFF, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Screenshot bewusst TIFF; noch mit Laborgerät testen

#### Tektronix TDS3000

    Profil-Key:        tektronix_tds30
    IDN-Erkennung:     TEKTRONIX und TDS30
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Best-effort aktiviert; konkretes Laborgerät noch offen

#### Tektronix MDO/MSO/DPO

    Profil-Key:        tektronix_mdo
    IDN-Erkennung:     TEKTRONIX und MSO4/MDO4/MDO3/DPO4
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Best-effort aktiviert; konkretes Laborgerät noch offen

#### Rohde & Schwarz / Hameg HMS-X Spectrum Analyzer

    Profil-Key:        rs_hameg_hms
    IDN-Erkennung:     HAMEG oder ROHDE plus HMS
    Funktionen:        Screenshot BMP, Trace CSV
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Gegen hochgeladenes HMS-X-SCPI-Manual geprüft; echten Gerätetest nachtragen

#### Rohde & Schwarz RT-Series, RTB/RTA/RTM/RTE/RTO/RTP

    Profil-Key:        rs_rt_scope
    IDN-Erkennung:     ROHDE plus RT-Modellkennung
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Gegen RTB2000-Manual geprüft; konkrete Modelle noch offen

#### Teledyne LeCroy WavePro/WaveRunner/SDA/Zi

    Profil-Key:        lecroy_xstream
    IDN-Erkennung:     LECROY/TELEDYNELECROY plus WAVEPRO/WAVERUNNER/SDA/ZI
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot BMP, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            commands from manual, untested
    Notizen:           LeCroy-Firmware/Schnittstelle kann variieren; noch mit Laborgerät testen

### Nicht Integriert

#### Pico Technology PicoScope 2206BMSO/2406B

    Profil-Key:        keines
    IDN-Erkennung:     keine
    Funktionen:        keine
    Status:            nicht integriert
    Notizen:           Bewusst ausgelassen, da typischerweise PicoSDK statt VISA/SCPI nötig ist

Für neue Rückmeldungen reicht es, den Status und die Notizen im jeweiligen Geräteblock zu aktualisieren. Sinnvoll sind kurze Einträge wie `getestet: IDN, Messwert, Screenshot ok; Waveform Fehler ...`.

## Hinweise

Der Python-Launcher `py` ist auf diesem Rechner vorhanden und die Python-Quellen wurden syntaktisch geprüft. Die Gerätetreiber-/VISA-Installation und ein angeschlossenes Messgerät sind für einen echten Kommunikationstest erforderlich.

Hardware-unabhängige Tests liegen unter `tests/` und nutzen ein Fake-Instrument. Damit werden Profil-Erkennung, wichtige SCPI-Befehlsfolgen und Screenshot-Binärdaten-Normalisierung geprüft, ohne echte Messgeräte anzusprechen.
