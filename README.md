# Measurement Devices Communication Library

Standalone-Python-Projekt zur Ablösung des vorhandenen VBA-Add-ins für Messgerätekommunikation.

## Ziel

Das Projekt kommuniziert per VISA/SCPI mit Messgeräten, liest Messwerte, Screenshots, Waveforms oder S-Parameter aus und schreibt die Ergebnisse in eine Excel-Datei. Binärdaten wie Screenshots werden zusätzlich als Datei neben der Excel-Datei abgelegt und in Excel referenziert.

## Installation

1. Python 3.10 oder neuer installieren.
2. Eine VISA-Runtime installieren, falls USB/GPIB/TCPIP-Geräte darüber angebunden sind. Empfohlen ist die schlanke R&S VISA Runtime: [R&S VISA und Tools](https://www.rohde-schwarz.com/de/driver-pages/fernsteuerung/3-visa-und-tools_231388.html). Alternativ funktionieren auch NI-VISA oder Keysight VISA über die Keysight IO Libraries Suite.
3. Abhängigkeiten installieren:

```powershell
py -m pip install -e .
```

Für Saleae-Unterstützung bei Python-Installationen zusätzlich das optionale Extra installieren:

```powershell
py -m pip install -e ".[saleae]"
```

Hinweis für GPIB: Der GPIB-Controller-Treiber sollte zur verwendeten VISA-Installation passen. Bei einem NI-GPIB-Adapter ist NI-VISA häufig die robustere Wahl.

## Externe Runtime-Abhängigkeiten

Externe Hersteller-Installer können lokal im Ordner `dependencies` gesammelt werden, z. B. R&S VISA Runtime, Keysight IO Libraries Suite, PicoSDK 64-bit mit ps2000a-Treiber und Saleae Logic 2. Das Paketier-Skript erzeugt daraus einen separaten Dependencies-Verteilerordner, wenn der Ordner lokal vorhanden ist.

Die fertige EXE enthält die Anwendung und Python-Abhängigkeiten, aber keine Windows-Treiber und keine Hersteller-Runtimes. Kollegen sollten nicht wahllos alle Installer ausführen, sondern nur die Pakete installieren, die zum Messgerät und Anschluss passen.

Kurze Zuordnung für Ziel-PCs:

| Gerät / Anschluss | Benötigte Installation |
| --- | --- |
| Normales Messgerät per USB, LAN oder GPIB | Eine VISA Runtime, empfohlen `RS_VISA_Setup_Win_<version>.exe` |
| Keysight/Agilent-Gerät | `IOLibrariesSuite-<version>-windows-x64.exe`, besonders wenn das Gerät mit R&S VISA nicht gefunden wird |
| R&S/Hameg HMS/HMP mit USB-Interface | R&S VISA plus bei Bedarf `HO720-HO730-Interface-Driver-<version>.zip` oder `HO732-USB-Driver-<version>.zip` |
| PicoScope 2206BMSO/2406B | `PicoSDK_x64_<version>.exe` |
| Saleae Logic Analyzer | `Logic-<version>-windows-x64.exe`, Logic 2 muss laufen und Automation muss aktiv sein |
| USB-RS232-/COM-Port-Verbindung | Passender USB-Seriell-Treiber, bei FTDI-Adaptern `CDM<version>_Setup.zip` |
| ältere GPIB-Geräte über USB-GPIB-Adapter | VISA Runtime plus Treiber des konkreten USB-GPIB-Adapters |

Das Paketier-Skript sortiert den Dependencies-Verteilerordner zusätzlich in nummerierte Ordner wie `1_Immer_zuerst_VISA`, `4_Falls_PicoScope` und `5_Falls_Saleae`. Die Datei `dependencies/INSTALLATION_KOLLEGEN.md` ist die kurze Anleitung für Anwender ohne Entwicklungsdetails.

Die vollständige Zuordnung aller unterstützten Geräteprofile zu Runtime, Treiber und Zusatzsoftware steht in `dependencies/README.md` im Abschnitt `Abdeckung der unterstuetzten Geraeteprofile`.

Empfohlene Struktur:

- `dependencies/`
- `dependencies/RS_VISA_Setup_Win_<version>.exe`
- `dependencies/IOLibrariesSuite-<version>-windows-x64.exe`
- `dependencies/PicoSDK_x64_<version>.exe`
- `dependencies/Logic-<version>-windows-x64.exe`
- `dependencies/HO720-HO730-Interface-Driver-<version>.zip`
- `dependencies/HO732-USB-Driver-<version>.zip`
- `dependencies/CDM<version>_Setup.zip`
- `dependencies/Treiber USB-GPIB.7z`
- `dependencies/INSTALLATION_KOLLEGEN.md`

Auf Zielrechnern müssen diese Systemkomponenten separat installiert werden, bevor die jeweilige Hardware genutzt werden kann.

## EXE-Build

Für die Weitergabe an Kollegen kann eine Windows-EXE mit PyInstaller gebaut werden. Die VISA-Runtime muss trotzdem auf dem Zielrechner installiert sein; die EXE enthält nur das Python-Tool und dessen Python-Abhängigkeiten.

```powershell
scripts\build_exe.ps1
```

Das Skript installiert ohne `-SkipInstall` das Projekt per `py -m pip install -e ".[saleae]"` inklusive Abhängigkeiten und aktualisiert anschließend `pyinstaller`. Dadurch enthält die EXE auch das Python-Paket für Saleae Logic 2 Automation. Danach entfernt es alte Build-Artefakte und erzeugt eine Onedir-Anwendung unter:

```text
dist\MeasurementDevicesCommunicationLibrary\MeasurementDevicesCommunicationLibrary.exe
```

Der Ordner `dist\MeasurementDevicesCommunicationLibrary` kann anschließend als ZIP weitergegeben werden. `README.md` und `config.example.ini` werden mit in den Ordner kopiert. Externe Runtime-Installer werden nicht in den EXE-Ordner kopiert; für diese erzeugt `scripts\package_release.ps1` einen separaten Dependencies-Verteilerordner.

Für sauber benannte Verteilerordner kann das Paketier-Skript ausgeführt werden. Es baut standardmäßig zuerst die EXE neu und erzeugt danach getrennte Verteilerordner und ZIP-Dateien für EXE, Python-Source und optional externe Runtime-Abhängigkeiten:

```powershell
scripts\package_release.ps1
```

Die Release-Struktur ist dadurch einfacher getrennt weiterzugeben:

- `release/MeasurementDevicesCommunicationLibrary_EXE_Windows_<datum>/`
- `release/MeasurementDevicesCommunicationLibrary_EXE_Windows_<datum>.zip`
- `release/MeasurementDevicesCommunicationLibrary_Python_Source_<datum>/`
- `release/MeasurementDevicesCommunicationLibrary_Python_Source_<datum>.zip`
- `release/MeasurementDevicesCommunicationLibrary_Dependencies_<datum>/`, falls `dependencies/` vorhanden ist
- `release/MeasurementDevicesCommunicationLibrary_Dependencies_<datum>.zip`, falls `dependencies/` vorhanden ist

Wenn Projektabhängigkeiten inklusive `logic2-automation` und `pyinstaller` bereits in der verwendeten Python-Umgebung vorhanden sind, geht es schneller mit:

```powershell
scripts\package_release.ps1 -SkipInstall
```

Falls nur aus einem bereits vorhandenen `dist\MeasurementDevicesCommunicationLibrary` paketiert werden soll:

```powershell
scripts\package_release.ps1 -SkipExeBuild
```

Es erzeugt Ordner und ZIP-Dateien unter `release\`:

```text
MeasurementDevicesCommunicationLibrary_EXE_Windows_<Datum>
MeasurementDevicesCommunicationLibrary_EXE_Windows_<Datum>.zip
MeasurementDevicesCommunicationLibrary_Python_Source_<Datum>
MeasurementDevicesCommunicationLibrary_Python_Source_<Datum>.zip
MeasurementDevicesCommunicationLibrary_Dependencies_<Datum>
MeasurementDevicesCommunicationLibrary_Dependencies_<Datum>.zip
```

Existiert ein Release-Ordner für das Datum bereits, hängt das Skript automatisch einen Zeitstempel an den Ordnernamen an.

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
instrument-visa generator-read --config config.ini
instrument-visa generator-set --frequency "100 MHz" --power "-30 dBm" --rf off --max-power 0 --config config.ini
instrument-visa generator-rf --rf off --config config.ini
instrument-visa sequence-run --sequence-file ablauf.json --output results.xlsx
```

`instrument-visa list` zeigt VISA-Ressourcen sowie zusätzlich direkt gefundene Windows-COM-Ports, PicoScope-2000A-Geräte und eine laufende Saleae-Logic-2-Automation an.

## Oberfläche

Nach `py -m pip install -e .` kann die Oberfläche aus dem Projektordner so gestartet werden:

```powershell
py -m instrument_visa.gui
```

Alternativ steht nach der Installation dieser Befehl zur Verfügung:

```powershell
instrument-visa-gui
```

Zusätzlich stehen nach der Installation die neuen Aliasse zur Verfügung:

```powershell
measurement-devices
measurement-devices-gui
```

Die Oberfläche bietet Geräte-Suche, Setup-Prüfung, IDN-Test, Gerät-aus-Liste-entfernen, DMM-Messwert, Scope-Messwert, getimtes Messen, Screenshot, Waveform-Export, S-Parameter-Export, Signalgenerator-Basisbedienung, Netzgerät-Basisbedienung, getimtes Schalten für Generatoren/Netzgeräte, 34970A-Datenlogger-Messungen, Spektrumanalysator-Trace-Export und automatische Abläufe in eine auswählbare Excel-Datei. Nach `IDN testen` wird ein Geräteprofil erkannt und die passenden Bereiche werden aktiviert. Für Oszilloskope sollte `Scope Messwert` genutzt werden, da `DMM Messwert` den Multimeter-Befehl `:READ?` sendet. Beim Waveform-Export können `CH1` bis `CH4` beliebig kombiniert werden. Zusätzlich ist der Punktmodus `RAW`, `NORMAL` oder `MAXIMUM` auswählbar. Jede Waveform-Messung wird zur besseren Übersicht in ein eigenes Tabellenblatt geschrieben.

Der Button `Setup prüfen` im Bereich `Verbindung` prüft das Zielsystem auf VISA Runtime, gefundene VISA-Ressourcen, COM-Ports, PicoSDK 2000A und Saleae Logic-2-Automation. Das Ergebnis wird als Diagnosefenster angezeigt und enthält konkrete Empfehlungen, welche Runtime oder welcher Treiber fehlt. Wenn Ressourcen gefunden werden, wird die Geräteauswahl in der Oberfläche direkt aktualisiert. Für Details zu konkreten Gerätefamilien auf Ziel-PCs siehe `dependencies/INSTALLATION_KOLLEGEN.md`.

Der Signalgenerator-Bereich kann Frequenz, Pegel und RF-Ausgang lesen bzw. setzen. Als Sicherheitsvorgabe ist der RF-Ausgang vor Änderungen abschaltbar und der Maximalpegel wird lokal geprüft, bevor Befehle gesendet werden. `RF Aus` sendet nur den Ausgang-Aus-Befehl und liest anschließend die aktuellen Einstellungen zurück. SME/SMT/SMIQ nutzen SCPI-Basisbefehle `:SOUR:FREQ:CW`, `:SOUR:POW` und `:OUTP`. SMGU/SMHU nutzen laut Programmierbeispielen die ältere IEC-Bus-Syntax `RF`, `LEVEL:RF`, `LEVEL:RF:ON` und `LEVEL:RF:OFF`.

Der Netzgerät-Bereich unterstützt R&S/Hameg HMP-Geräte wie HMP4030. Pro Kanal können Spannung und Stromlimit gesetzt, Soll-/Istwerte gelesen und der ausgewählte Ausgang aktiviert oder deaktiviert werden. Wenn ein HMP-Gerät sowohl als direkter Windows-COM-Port als auch als VISA-ASRL-Ressource gefunden wird, sollte die VISA-ASRL-Adresse verwendet werden, z. B. `ASRL4::INSTR`. Als Sicherheitsgrenzen werden Maximalspannung und Maximalstrom lokal geprüft, bevor Befehle gesendet werden. Die Implementierung nutzt `INST:NSEL`, `VOLT`, `CURR`, `MEAS:VOLT?`, `MEAS:CURR?`, `OUTP:SEL` und `OUTP:GEN`.

Der Bereich `Getimtes Schalten` wird für Signalgenerator- und Netzgeräteprofile eingeblendet. Er kann RF bzw. Netzgeräteausgänge mit einstellbarer ON-/OFF-Dauer und Wiederholungszahl schalten. Optional wird vor dem Schalten ein sicherer Startzustand gesetzt; am Ende kann der Ausgang automatisch abgeschaltet werden.

Der `34970A Datenlogger`-Bereich unterstützt Agilent/HP/Keysight 34970A/34972A über direkte Windows-COM-Ports oder VISA-ASRL-Adressen. Für das getestete Setup sind die Defaults `19200`, `8N1`, Messplan `1-20:TEMP; 21-22:CURR_DC`, Intervall `5 s` und Anzahl `0=endlos`. `Kanäle messen` misst eine Messart über die eingetragenen Kanäle; `Messplan messen` führt gemischte Kanalgruppen aus. Die Messung läuft wiederholt bis zur eingestellten Anzahl oder bis `Stop`. Ergebnisse werden zeilenweise in das Excel-Blatt `34970A Measurements` geschrieben, mit `Timestamp` und Kanälen nebeneinander, z. B. `CH1 TEMP [degC]` bis `CH22 CURR_DC [A]`. Nach erfolgreichem `IDN testen` werden funktionierende serielle Einstellungen gespeichert und beim nächsten Zugriff bevorzugt verwendet.

Der `Spektrumanalysator`-Bereich wird für erkannte Spektrumanalysator-Profile eingeblendet. `Trace exportieren` nutzt die bestehende Waveform-/Trace-Logik des Geräteprofils; `Screenshot` ist nur aktiv, wenn das Profil Hardcopy/Screenshot unterstützt.

Der Bereich `Automatischer Ablauf` öffnet über `Freier Ablauf-Editor` ein eigenes Fenster, in dem mehrere Geräte benannt, einzelne Schritte in eine Ablauf-Liste eingefügt und mit Wiederholungen, Pause sowie einer optional pro Durchlauf hochgezählten Variable ausgeführt werden können. Unterstützt sind Generator-Frequenz/Pegel/RF, Netzgerät-Spannung/Ausgänge, DMM-Messwert, Scope-Messwert, Scope-/Spektrumanalysator-Waveform/Trace, Screenshots, serielle Logs von ASRL/COM-Geräten, einfache Parallel-Messphasen und Wartezeiten. Im Gerätebereich des freien Editors können vorhandene Windows-COM-Ports über `COM-Port` und `suchen` ermittelt und mit `übernehmen` direkt als serielles Gerät eingetragen werden, z. B. `COM3` oder `COM12`; manuelles Eintragen bleibt möglich. Für VISA-Seriell geht weiterhin eine Adresse wie `ASRL3::INSTR`. Der Schritt `Seriellen Log aufzeichnen` liest passiv mit und bietet `Dauer [s]`, `Baudrate` und `Format`, z. B. `8N1`, `7E1`, `7O1`, `7E2`, `8E1`, `8O1` oder `8N2`. Der Schritt `Parallel-Messphase` startet mehrere einfache Aufgaben gleichzeitig über eine Dauer und ein Messintervall; Aufgaben werden mit Semikolon getrennt eingetragen, z. B. `DMM1:dmm; Scope1:scope:Vpp:1; Seriell1:serial:115200:8N1`. DMM- und Scope-Werte werden in ein eigenes Tabellenblatt geschrieben, serielle Parallel-Logs zusätzlich als Textdatei exportiert. Variablen werden in Parametern als `${name}` verwendet, z. B. `${frequency}` oder `${voltage}`. Der freie Ablauf wird als eigenes Excel-Tabellenblatt mit Durchlauf, Schritt, Gerät, Aktion, Parametern, Wert und Status gespeichert. Serielle Logs werden zusätzlich als Textdatei neben der Excel-Datei abgelegt und im Ergebnisblatt referenziert. Der Editor enthält Vorlagen für getimtes DMM- und Scope-Messen, RF- und Netzteil-Schalten, Generator+DMM, Generator+Oszilloskop, Netzteil+DMM, Netzteil+Oszilloskop, Generator+Spektrumanalysator, Screenshot, Kurve/Trace, Parallel-Messphase, serielles Kommando mit Log, SSH-Kommando, PicoScope analog, Saleae UART, 34970A-Messplan und CA-410-Messwert; fertige Abläufe können als JSON importiert und exportiert werden. Exportierte JSON-Abläufe können über die Kommandozeile mit `instrument-visa sequence-run --sequence-file <datei.json> --output <xlsx>` ausgeführt werden. Die bisherigen Spezialbereiche für getimtes Messen, getimtes Schalten sowie die alten festen Sweep-Eingaben im Hauptfenster sind zugunsten des freien Editors ausgeblendet.

Aktueller Hinweis zum freien Ablauf: Als serielle Formate sind `8N1`, `7E1`, `7O1`, `7E2`, `8E1`, `8O1` und `8N2` auswählbar. Serielle Logs werden als Textdatei neben der Excel-Datei abgelegt. Saleae-Aufnahmen werden im Ordner `<excelname>_artifacts` abgelegt. PicoScope-Aufnahmen werden als CSV-Inhalt in Excel-Tabellenblätter exportiert.

Zusätzlich zum passiven Schritt `Seriellen Log aufzeichnen` unterstützt der freie Ablauf-Editor den Schritt `Serielles Kommando senden`. Damit kann für COM-Ports und VISA-ASRL-Geräte beliebiger Text gesendet werden; Escape-Sequenzen wie `\r`, `\n` und `\t` werden in echte Steuerzeichen umgewandelt, sodass z. B. `*IDN?\n` oder gerätespezifische ASCII-Protokolle möglich sind. Optional zeichnet `Antwort lesen [s]` direkt nach dem Senden für eine feste Zeit die Antwort auf; ohne Antwortzeit wird nur gesendet. Das ist für Spezialgeräte gedacht, die zwar als serielles Interface erkannt werden, aber kein eigenes Geräteprofil haben.

Der freie Ablauf-Editor bietet bis zu zwölf Wertefelder pro Schritt. Dadurch sind beim CA-410-Schritt neben Farbmodus, Probe, Kalibrierkanal, Messmethode, Sync und Integration auch Flicker-Methode, Messgeschwindigkeit, Baudrate und serielles Format direkt einstellbar.

Der freie Ablauf-Editor unterstützt außerdem SSH-Geräte. Dafür ein Gerät mit Adresse im Format `ssh://user@host` oder `ssh://user@host:2222` eintragen und den Schritt `SSH: Kommando ausführen` verwenden. Der Schritt bietet Kommando, optional abweichenden Benutzer, optional Passwort und Timeout in Sekunden. Ohne Passwort nutzt die SSH-Bibliothek vorhandene SSH-Keys bzw. den Agent; mit Passwort wird Passwort-Authentifizierung verwendet. Die Standardausgabe des Kommandos wird als Schrittwert in das Ablauf-Ergebnis geschrieben, ein nicht-null Exit-Code bricht den Schritt mit Fehlerstatus ab.

Die Vorlagen im freien Ablauf-Editor decken typische Startszenarien ab: getimtes Multimeter- oder Oszilloskop-Messen, RF-Schalten, Netzgerät-Schalten, Generator- oder Netzgerät-Sweeps mit DMM/Scope/Spektrumanalysator, Screenshot speichern, Kurve/Trace speichern, Parallel-Messphase, serielles Kommando mit anschließendem Log, SSH-Kommando, PicoScope-Analogaufnahme, Saleae-UART-Aufnahme, 34970A-Messplan und CA-410-Messwert. Die Vorlagen sind bewusst einfache Ausgangspunkte; danach können Geräteadressen, Parameter, Wiederholungen und Variablen angepasst und als JSON exportiert werden.

Beispielhafte Ablauf-Szenarien:

- Generator-Sweep mit DMM: `Signalgenerator: Frequenz setzen`, `Warten`, `Multimeter: Messwert lesen`; Variable `${frequency}` pro Durchlauf erhöhen.
- Netzgerät-Sweep mit Scope: `Netzgerät: Spannung/Strom setzen`, `Warten`, `Oszilloskop: Messwert lesen`; Variable `${voltage}` pro Durchlauf erhöhen und `Netzgerät am Ende aus` aktivieren.
- Trace- oder Waveform-Export: `Oszilloskop/Spektrum: Kurve erfassen`, optional nach einem Generator- oder Netzgerät-Schritt.
- Screenshot-Dokumentation: `Gerät: Screenshot erfassen`, z. B. nach einer Messphase oder einem Gerätezustand.
- Serielle Spezialgeräte: `Serielles Kommando senden` mit z. B. `*IDN?\n` oder gerätespezifischem ASCII-Kommando, danach optional `Seriellen Log aufzeichnen`.
- SSH-gesteuerte Prüflinge: `SSH: Kommando ausführen`, z. B. Dienst starten, DUT konfigurieren oder Logdatei abfragen, danach Messgerät-Schritte ausführen.
- Parallel-Messphase: DMM, Scope und serielles Log gleichzeitig für eine feste Dauer erfassen, z. B. `Multimeter1:dmm; Oszilloskop1:scope:Vpp:1; Seriell1:serial:115200:8N1`.
- Datenlogger: `Agilent 34970A: Messplan` mit gemischten Kanalgruppen wie `1-20:TEMP; 21-22:CURR_DC`.
- Logic Analyzer: `Saleae: Digital aufnehmen` und anschließend Analyzer-Schritte wie `Saleae: UART dekodieren`.
- PicoScope: `PicoScope: Analog erfassen` oder `PicoScope: Digital erfassen`, wenn ein PicoScope ohne VISA-SCPI genutzt wird.

Beim getimten Messen kann eine DMM- oder Scope-Messreihe mit Intervall in Sekunden und Anzahl Messpunkte gestartet werden. Die Messpunkte werden auf feste Sollzeitpunkte geplant, damit die Messdauer das Intervall nicht dauerhaft verschiebt. Die Messreihe kann über `Stop` abgebrochen werden. Die Ergebnisse werden mit Index, Zeitstempel, verstrichener Zeit, Delta zum vorherigen Messpunkt, Abweichung vom Sollzeitpunkt, Messart, Kanal, Wert und Status in ein eigenes Tabellenblatt geschrieben. Zusätzlich enthält das Tabellenblatt eine Zusammenfassung mit Start-/Endzeit, Soll-Intervall, angeforderter und tatsächlicher Anzahl sowie OK- und Fehlerzähler.

Die GUI merkt sich zuletzt verwendete Einstellungen in `gui_settings.json`, darunter VISA-Adresse, bekannte Geräte, Excel-Datei, Scope-Messung, Timed-Measurement-Intervall, Timed-Measurement-Anzahl, Waveform-Kanäle, Waveform-Punktmodus, S-Parameter-Auswahl und 34970A-Datenlogger-Einstellungen. Nach einer erfolgreichen IDN-Abfrage wird die VISA-Adresse zusammen mit IDN, Gerätetyp, Profil und unterstützten Funktionen gespeichert. Für serielle Geräte können zusätzlich erfolgreiche SCPI-Settings wie Baudrate, Format, Flow-Control und Terminator gespeichert werden. Bekannte Geräte erscheinen beim nächsten Start direkt in der Geräte-Liste mit Typ, Hersteller, Modell und Adresse. Bei einer neuen Gerätesuche werden die gefundenen VISA-Adressen mit den bekannten Geräten zusammengeführt, sodass bereits erkannte Geräte sofort mit Typ angezeigt und die passenden Bedienbereiche aktiviert werden. Dabei werden äquivalente `ASRL...::INSTR`-Adressen gegenüber direkten `COM`-Adressen bevorzugt; direkte `COM`-Adressen bleiben für serielle Logs und Geräte ohne VISA-ASRL-Zugriff möglich. Die Auswahl eines bekannten Geräts nutzt das gespeicherte Profil ohne automatische IDN-Abfrage; für eine erneute Erkennung kann `IDN testen` manuell gestartet werden. Die Buttons `Excel öffnen` und `Ordner öffnen` öffnen direkt die Ergebnisdatei bzw. den Ausgabeordner. Der Excel-Export ergänzt Zeitstempel, Metadaten und eigene Tabellenblätter für Waveform- und Messreihendaten. Waveform-Tabellenblätter bekommen automatisch ein Diagramm, wenn numerische Daten erkannt werden. PNG-Screenshots werden zusätzlich in ein eigenes Excel-Tabellenblatt eingebettet.

Wenn `IDN testen` bei einem direkten `COM...`-Port oder einer `ASRL...::INSTR`-Adresse keine bekannte Geräte-ID erkennt, wird die Adresse als `Seriell` abgelegt und nicht als unbekanntes Messgerät. Damit werden nicht versehentlich DMM-/Scope-Bereiche aktiviert; solche Geräte können anschließend im freien Ablaufeditor über `Seriell: Kommando senden` oder `Seriell: Log aufzeichnen` genutzt werden.

Alle GUI- und CLI-Aktionen werden dauerhaft in `logs/instrument_visa.log` protokolliert. Das Log enthält gestartete Aktionen, Exportpfade, erkannte Geräteprofile und vollständige Fehlerdetails.

## Aus dem VBA-Projekt übernommene Funktionen

- VISA-Initialisierung und `*IDN?`-Abfrage
- Geräteerkennung über IDN-String
- Screenshots für E740, E5071C, FSW, Keysight/Agilent DSO/MSO/MSOX, PXA/MXA/EXA/CXA, ZNB und Tektronix-Geräte
- Waveform-/Messwertausgabe für E740, 4395A, Keysight/Agilent 3000X/MSOX/6000/7000 und 344xx/L44xx
- S-Parameter-Dateien für E5071C und R&S ZNB
- Excel-Ausgabe per `openpyxl`
- 34970A-Datenlogger-Defaults aus dem VBA-Projekt: Kanäle `1-20` Temperatur, Kanäle `21-22` Strom, serielle Defaults `19200 8N1`, kanalweise Ausgabe mit Messzeitpunkt

## Geräteunterstützung

Die folgenden Geräteprofile sind mit realen Geräten aus diesem Projekt getestet oder aus dem vorhandenen VBA-Projekt übernommen:

- Keysight/Agilent 344xx/L44xx, darunter 34461A und 34401A: DMM-Messwert und getimtes DMM-Messen über `:READ?`

Hinweis zum Keysight/Agilent 34461A über USB: Wenn das Gerät direkt nach dem Start der App oder nach dem Einschalten nicht in `Geräte suchen` erscheint, hilft in der Praxis häufig, das USB-Kabel am Gerät einmal kurz abzuziehen und wieder einzustecken und danach `Geräte suchen` erneut auszuführen. Falls das weiterhin nötig ist, auch Keysight Connection Expert bzw. die verwendete VISA Runtime prüfen.
- Keysight/Agilent InfiniiVision X-Series, darunter DSOX2024A und MSOX3054T: Scope-Messwert, getimtes Scope-Messen, Screenshot und Waveform-Export
- Keysight/Agilent E5071C: Screenshot und S-Parameter-Export
- Rohde & Schwarz ZNB: Screenshot und S-Parameter-Export
- Keysight/Agilent/HP E740 und HP/Agilent 4395A: Exportfunktionen aus dem VBA-Projekt
- Agilent/HP/Keysight 34970A/34972A: Datenlogger-Messplan über serielle COM-Verbindung, getestet mit `HEWLETT-PACKARD,34970A,0,13-2-2`
- Konica Minolta CA-410: Messwert über virtuellen COM-Port getestet

Die folgenden Geräteprofile sind als best-effort implementiert, aber noch nicht mit den konkreten Laborgeräten getestet. Die SCPI-Befehle wurden gegen öffentlich verfügbare Programmierhandbücher bzw. Hersteller-Manual-Seiten gegengeprüft, soweit zugänglich. Sie erscheinen nach `IDN testen` mit Gerätetyp und aktivierten Funktionen; Rückmeldungen aus Tests sollten im Log `logs/instrument_visa.log` geprüft werden:

- Keysight/Agilent InfiniiVision 6000, darunter MSO6034A/DSO6034A: Scope-Messwert, getimtes Scope-Messen, Screenshot und Waveform-Export mit 6000-Series-Programmer-SCPI (`:MEASure...`, `:WAVeform...`, `:DISPlay:DATA?`)
- Keysight/Agilent InfiniiVision 7000, darunter DSO7034B/MSO7034: Scope-Messwert, getimtes Scope-Messen, Screenshot und Waveform-Export mit 7000-Series-Programmer-SCPI (`:MEASure...`, `:WAVeform...`, `:DISPlay:DATA? PNG, SCREEN, COLOR`)
- HP/Agilent 54600/54620, darunter 54622D: Scope-Messwert, Screenshot und Waveform-Export mit 54620-Series-Programmer-SCPI. Screenshot nutzt BMP, da das 54622D-Manual bei `:DISPlay:DATA?` nur `TIFF | BMP` nennt.
- HP 8591A: Trace-A-Export best-effort über alten HP-IB-Befehl `TRA?`. Screenshot/Hardcopy ist als HP-GL/Plotter-Capture über `GETPLOT` aktiviert und wird als `.hpgl` abgelegt.
- Agilent E4402B ESA: Screenshot WMF und Trace CSV best-effort über ESA/E740-ähnliche SCPI-/Mass-Memory-Befehle (`:MMEM:STOR:SCR`, `:MMEM:STOR:TRAC TRACE1,"R:<temp>.CSV"`, `:MMEM:DATA?`). Temporäre Dateien auf dem Gerät bekommen eindeutige Namen und werden nach dem Auslesen gelöscht.
- Keithley 2000: DMM-Messwert und getimtes DMM-Messen über `:READ?`, laut Keithley-Manual als `:ABORt`, `:INITiate`, `:FETCh?`-Sequenz beschrieben
- Tektronix TDS400, darunter TDS420A: Scope-Messwert, Screenshot und Waveform-Export mit TDS-Family-Programmer-SCPI (`MEASUrement:IMMed...`, `DATa:SOUrce`, `DATa:ENCdg ASCii`, `CURVe?`, `HARDCopy START`). Screenshot nutzt TIFF, da PNG im TDS400A-Manual nicht als sicher unterstütztes Hardcopy-Format aufgeführt ist.
- Tektronix TDS3000/MDO/MSO/DPO: Scope-Messwert und Screenshot best-effort aktiviert; Waveform-Export ist aktuell nur für TDS400 aktiviert
- Rohde & Schwarz / Hameg HMS-X: Screenshot und Trace-Export mit HMS-X-SCPI-Programmer-Manual gegengeprüft (`HCOPy:FORMat BMP`, `HCOPy:DATA?`, `TRACe:DATA:FORMat CSV`, `TRACe:DATA?`). Screenshot nutzt BMP, da das Manual nur BMP für `HCOPy:FORMat` aufführt.
- Rohde & Schwarz / Hameg HMP4030/HMP4040/HMP2000: Netzgerät-Basisbedienung mit Kanalwahl, Spannung, Stromlimit, Ausgangsschaltung und Messwertabfrage über HMP-SCPI (`INST:NSEL`, `VOLT`, `CURR`, `MEAS:VOLT?`, `MEAS:CURR?`, `OUTP:SEL`, `OUTP:GEN`).
- Rohde & Schwarz SME/SMT/SMIQ: IDN-/Profil-Erkennung als Signalgeneratoren sowie Basisbedienung für Frequenz, Pegel und RF-Ausgang über `:SOUR:FREQ:CW`, `:SOUR:POW` und `:OUTP`. Die Langformen sind laut Manuals `[:SOURce]:FREQuency[:CW|:FIXed]`, `[:SOURce]:POWer[:LEVel][:IMMediate][:AMPLitude]` und `:OUTPut[:STATe]`.
- Rohde & Schwarz SMGU/SMHU: IDN-/Profil-Erkennung als Legacy-Signalgeneratoren sowie Basisbedienung über die im Manual gezeigte IEC-Bus-Syntax `RF`, `LEVEL:RF`, `LEVEL:RF:ON` und `LEVEL:RF:OFF`.
- Rohde & Schwarz RT-Series-Oszilloskope, falls IDN `RTB`, `RTA`, `RTM`, `RTE`, `RTO` oder `RTP` enthält: Scope-Messwert, Screenshot und Waveform mit RTB2000-Manual-SCPI (`MEASurement...`, `HCOPy:DATA?`, `CHANnel:DATA?`)
- Teledyne LeCroy WavePro/WaveRunner/SDA/Zi: Scope-Messwert, Screenshot und Waveform-Export mit X-Stream/WaveRunner-Remote-Control-SCPI (`PAVA?`, `SCREEN_DUMP`, `INSPECT? "SIMPLE"`)

PicoScope 2206BMSO und PicoScope 2406B können im freien Ablauf über `PICO2000A::AUTO` oder `PICO2000A::SERIAL::<seriennummer>` angesprochen werden. Dafür muss auf dem Ziel-PC das PicoSDK 64-bit mit ps2000a-Treiber installiert sein; ohne PicoSDK bleibt das Programm startfähig, PicoScope-Schritte melden dann eine klare Fehlermeldung. Unterstützt sind zunächst analoge Block-Aufnahmen über `PicoScope: Analog erfassen` mit Bereich, Sample-Anzahl und Intervall in Mikrosekunden. Beim 2206BMSO sind typischerweise `A,B` analog und zusätzlich digitale MSO-Kanäle `D0-D15` nutzbar; beim 2406B sind typischerweise `A,B,C,D` analog nutzbar, aber keine MSO-Digitalkanäle. Digitale Aufnahmen laufen über `PicoScope: Digital erfassen` mit Kanälen, Logikpegel, Samples und Intervall. Die Ergebnisse werden als CSV/Excel-Waveform exportiert.

Agilent/HP/Keysight 34970A/34972A Datenlogger können im freien Ablauf über `Agilent 34970A: Kanäle messen` genutzt werden. Für USB-Seriell-Adapter kann direkt ein Windows-COM-Port wie `COM5` als Geräteadresse eingetragen werden; alternativ funktioniert eine VISA-ASRL-Adresse wie `ASRL5::INSTR`. Unterstützt sind Kanäle `1-22` sowie Messarten `VOLT_DC`, `RES`, `FRES`, `CURR_DC` und `TEMP`. Die Kanalangabe kann einzelne Kanäle und Bereiche enthalten, z. B. `1-4,7,10-12`; intern werden daraus die SCPI-Kanäle `101` bis `122`, die pro Messart in einem gemeinsamen SCPI-Query abgefragt werden. Der Schritt bietet Messart, Kanäle, Baudrate und serielles Format. Wenn pro Kanal oder Kanalgruppe unterschiedliche Messarten nötig sind, kann `Agilent 34970A: Messplan` verwendet werden, z. B. `1-4:VOLT_DC; 5-8:TEMP; 9-12:RES; 13-14:CURR_DC`. Thermoelemente verwenden zunächst Typ `K`. Für `VOLT_DC` werden bei `AUTO`/`DEF` die getesteten Parameter Bereich `10` und Auflösung `0.003` verwendet; andere Messarten senden ohne explizite Bereichs-/Auflösungsparameter die Geräte-Defaults. Die Ergebnisse werden als CSV/Excel-Tabelle mit Kanal, Messart, Wert und Einheit exportiert. Die Implementierung basiert auf der 34970A/34972A Command Reference und wurde mit einem 34970A getestet.

Konica Minolta CA-410 Display Color Analyzer können über einen virtuellen COM-Port oder eine VISA-ASRL-Adresse genutzt werden. In der GUI den COM-Port auswählen und `Als CA-410` drücken; danach erscheint der Bereich `Konica Minolta CA-410`. Unterstützt ist das Lesen einzelner Messwerte mit den offiziellen CA-410-Kommandos `COM,1`, `OPR,<probe>`, `SCS,<sync>`, `FSC,<speed>`, `MMS,<method>`, `VSN,<integration>`, `FMS,<method>`, `MCH,<probe>,<channel>`, `MDS,<mode>` und `MES,2`. Standardparameter sind `38400`, `7E2`, RTS/CTS und CR-Abschluss. Einstellbar sind Probe, Kalibrierkanal `0..99`, Messmethode `Color+Flicker`, `Color` oder `Flicker`, Flicker-Methode `FMA` oder `JEITA`, Messgeschwindigkeit `SLOW`, `FAST`, `LTD.AUTO` oder `AUTO`, Sync-Modus `UNIV`, `INT`, `EXT`, `NTSC`, `PAL` oder `MANUAL`, Integration `Double-Frame` oder `Single-Frame`, eine optionale Averaging-Zeit in Sekunden sowie die Farbmodi `xyLv`, `TcpduvLv`, `uvLv`, `XYZ` und `AdPeLv`. Sinnvolle Voreinstellungen sind `UNIV`, `Double-Frame`, `FAST` und `Averaging 0 s`; `INT` nutzt den Sync-Wert als Frequenz in Hz, `MANUAL` als Integrationszeit in ms. `Single-Frame` ist nur für reine Farbmessung mit Sync `NTSC`, `PAL`, `EXT` oder `INT` sinnvoll und wird deshalb nur mit Messmethode `Color` und einem passenden Sync-Modus akzeptiert. Die Averaging-Zeit ist softwareseitig umgesetzt: Innerhalb der eingestellten Zeit werden mehrere `MES`-Messungen ausgeführt und numerische Ergebnisfelder gemittelt; bei `0 s` wird genau ein Messwert aufgenommen. Der Kalibrierkanal und die weiteren CA-410-Einstellungen werden in `gui_settings.json` gespeichert und beim nächsten Start wieder geladen. Zusätzlich werden, sofern vom Gerät geliefert, `X`, `Y`, `Z`, Temperaturdrift und FMA-Flicker-Prozentwert exportiert. Ergebnisse werden in das gemeinsame Excel-Blatt `CA-410 Measurements` geschrieben. Für USB-Verbindung benötigt Windows den Konica-Minolta-USB-Treiber für den virtuellen COM-Port; bei echter RS-232-Verbindung ist ggf. nur der USB-RS232-Adaptertreiber nötig. Die offizielle Communication-Specification-PDF liegt lokal unter `Manuals/CA-410_Communication_Specifications_V1.08.pdf`.

Saleae Logic Analyzer können im freien Ablauf über `SALEAE::LOCAL` als Geräteadresse vorbereitet werden. Dafür muss Saleae Logic 2 installiert sein und die Automation-Schnittstelle aktiviert sein, entweder in der Logic-2-Oberfläche oder per Start mit `Logic.exe --automation`; der Standardport ist `10430`. Für Python-Installationen wird zusätzlich das Extra `saleae` bzw. das Paket `logic2-automation` benötigt. EXE-Releases enthalten dieses Paket, sofern sie mit dem normalen Build-Skript ohne `-SkipInstall` gebaut wurden. Unterstützt sind `Saleae: Digital aufnehmen` mit Kanälen wie `D0-D7`, Dauer, Sample-Rate und Schwellwert sowie Analyzer-Schritte für `Saleae: UART dekodieren`, `Saleae: I2C dekodieren`, `Saleae: SPI dekodieren` und `Saleae: CAN dekodieren`. Die Saleae-Aufnahme wird als `.sal` gespeichert, Rohdaten bzw. Analyzer-Exporte werden als CSV im Ablauf-Artefaktordner `<excelname>_artifacts` abgelegt und im Ablauf-Ergebnis referenziert. Die Saleae-Automation-Dokumentation ist extern bei Saleae verfügbar; lokal abgelegte Manual-Kopien unter `Manuals\...` sind optional und werden nicht versioniert oder in Releases mitverteilt. Die Integration ist mit Hardware noch zu testen.

## Geräte-Testabläufe

Diese Abläufe sind für den ersten Labortest gedacht. Für neue oder noch ungetestete Geräte immer zuerst `IDN testen` ausführen, danach nur die im automatisch eingeblendeten Gerätebereich angebotenen Funktionen verwenden. Bei Generatoren und Netzgeräten mit niedrigem Pegel bzw. kleinen Grenzwerten starten. Fehler und gesendete Aktionen stehen im Log `logs/instrument_visa.log`.

### Allgemeiner Gerätetest

1. Gerät per USB, LAN oder GPIB/VISA verbinden.
2. In der GUI `Geräte suchen` ausführen.
3. VISA-Adresse auswählen.
4. `IDN testen` ausführen.
5. Erwartetes Profil und eingeblendete Bedienbereiche prüfen.
6. Zuerst eine ungefährliche Leseaktion ausführen, z. B. `DMM Messwert`, `Scope Messwert`, `Generator lesen` oder `Netzgerät lesen`.
7. Erst danach Schreibaktionen mit sicheren Defaults testen.

### R&S SME/SMT/SMIQ Signalgeneratoren

Erwartetes Profil: `rs_sme_smt_smiq`

GUI-Test:

1. `IDN testen` ausführen.
2. Bereich `Signalgenerator` muss sichtbar sein.
3. `Generator lesen` ausführen.
4. Für den ersten Schreibtest setzen:
   - Frequenz: `100 MHz`
   - Pegel: `-30 dBm`
   - RF: `OFF`
   - Max. Pegel: `0`
   - `RF vor Änderung aus`: aktiv
5. `Generator setzen` ausführen.
6. Wenn das erfolgreich ist, RF nur mit angeschlossenem geeigneten Abschluss oder Prüfling aktivieren.

Verwendete Befehle:

```text
:SOUR:FREQ:CW?
:SOUR:POW?
:OUTP?
:OUTP OFF
:SOUR:FREQ:CW <freq>
:SOUR:POW <level>
:OUTP ON|OFF
```

Erwartete Ausgabe: Excel-Tabellenblatt `SignalGenerator...` mit Frequenz, Pegel und RF-Status.

### R&S SMGU/SMHU Legacy-Signalgeneratoren

Erwartetes Profil: `rs_smg_legacy`

GUI-Test:

1. `IDN testen` ausführen.
2. Bereich `Signalgenerator` muss sichtbar sein.
3. Zuerst `Generator lesen` testen.
4. Für den ersten Schreibtest setzen:
   - Frequenz: `100 MHz`
   - Pegel: `-30DBM`
   - RF: `OFF`
   - Max. Pegel: `0`
5. `Generator setzen` ausführen.
6. Log prüfen, da ältere Geräte bei Antwortformaten variieren können.

Verwendete Befehle:

```text
RF?
LEVEL:RF?
LEVEL:RF:OFF
RF <freq>
LEVEL:RF <level>
LEVEL:RF:ON|OFF
```

Erwartete Ausgabe: Excel-Tabellenblatt `SignalGenerator...`. Rückmeldungen können je nach Firmware leicht anders formatiert sein.

### HP 8591A Spektrumanalysator

Erwartetes Profil: `hp_8591a`

GUI-Test:

1. `IDN testen` ausführen.
2. Bereich `Spektrumanalysator` mit `Screenshot` und `Trace exportieren` verwenden. Falls zusätzlich der Waveform-Bereich sichtbar ist, kann dort ebenfalls der Trace-Export getestet werden.
3. Zuerst `Waveform` testen. Das liest Trace A.
4. Danach `Screenshot` testen. Die Ausgabe ist HP-GL, kein Bitmap.

Verwendete Befehle:

```text
TRA?
GETPLOT
```

Erwartete Ausgabe:

- Trace: CSV-Daten in Excel mit `Point,TraceA`
- Screenshot/Hardcopy: zusätzliche `.hpgl`-Datei neben der Excel-Datei

Hinweis: `GETPLOT` liefert voraussichtlich Plotterdaten. Zum Anzeigen wird ein HP-GL-Viewer oder später ein Konverter nach SVG/PNG benötigt.

### Agilent E4402B ESA Spektrumanalysator

Erwartetes Profil: `hp_agilent_e4402b`

GUI-Test:

1. `IDN testen` ausführen.
2. `Waveform` testen, um Trace 1 als CSV zu exportieren.
3. `Screenshot` testen, um eine WMF-Datei zu exportieren.
4. Excel-Datei öffnen und prüfen, ob Trace und Artefaktlink angelegt wurden.

Verwendete Befehle:

```text
:SYST:TIME ...
:SYST:DATE ...
:DISP:MENU:STATE 0
:MMEM:STOR:TRAC TRACE1,"R:<temp>.CSV"
:MMEM:DATA? 'R:<temp>.CSV'
:MMEM:DEL 'R:<temp>.CSV'
:MMEM:STOR:SCR 'R:<temp>.WMF'
:MMEM:DATA? 'R:<temp>.WMF'
:MMEM:DEL 'R:<temp>.WMF'
```

Erwartete Ausgabe:

- Trace: CSV in Excel
- Screenshot: `.wmf`-Datei neben der Excel-Datei

### R&S/Hameg HMP4030/HMP4040/HMP2000 Netzgeräte

Erwartetes Profil: `rs_hmp_power_supply`

GUI-Test:

1. `IDN testen` ausführen.
2. Bereich `Netzgerät` muss sichtbar sein.
3. Kanal auswählen. HMP4030 hat 3 Kanäle, HMP4040 hat 4 Kanäle, HMP2020 hat 2 Kanäle.
4. `Netzgerät lesen` ausführen.
5. Für den ersten Schreibtest setzen:
   - Kanal: `1`
   - Spannung: `1 V`
   - Stromlimit: `0.1 A`
   - Ausgang: `OFF`
   - Max. V: passend zum Aufbau, z. B. `5`
   - Max. A: passend zum Aufbau, z. B. `0.5`
6. `Netzgerät setzen` ausführen.
7. `Kanal Aus` testet `OUTP:SEL 0` für den gewählten Kanal.
8. `Alle Aus` testet `OUTP:GEN 0` für den Master-Ausgang.

Verwendete Befehle:

```text
INST:NSEL <channel>
VOLT <voltage>
CURR <current>
VOLT?
CURR?
MEAS:VOLT?
MEAS:CURR?
OUTP:SEL 0|1
OUTP:SEL?
OUTP:GEN 0|1
OUTP:GEN?
```

Erwartete Ausgabe: Excel-Tabellenblatt `PowerSupply...` mit Sollspannung, Sollstrom, Istspannung, Iststrom, Kanalstatus und Masterstatus.

Sicherheit: Das Tool prüft Maximalspannung und Maximalstrom lokal, bevor Setzbefehle gesendet werden. Trotzdem sollten die Grenzwerte im Gerät und am Prüfling passend gesetzt sein.

### Automatischer Ablauf Mit Signalgenerator

Generator-Sweeps werden im Bereich `Automatischer Ablauf` über den Button `Freier Ablauf-Editor` erstellt. Der Ablauf ist für Tests wie `Generator einstellen -> Messgerät messen -> nächsten Frequenzpunkt` gedacht.

GUI-Test:

1. Generator und Messgerät separat mit `IDN testen` prüfen.
2. Im Bereich `Automatischer Ablauf` den `Freier Ablauf-Editor` öffnen.
3. Generator und Messgerät in der Geräteliste anlegen oder aus den gefundenen Geräten übernehmen.
4. Eine passende Vorlage wie `Generator + Multimeter` oder `Generator + Oszilloskop` einfügen.
5. Für den ersten Test kleine Punktzahl wählen:
   - Start: `100 MHz`
   - Stop: `102 MHz`
   - Schritt: `1 MHz`
   - Pegel: `-30 dBm`
   - Wartezeit: `0.5`
   - Messart: `DMM` oder `Scope`
   - `RF am Ende aus`: aktiv
6. `Ablauf starten` ausführen.
7. Bei Bedarf `Stop` drücken. RF wird bei Stop oder Fehler sicherheitshalber ausgeschaltet.

Erwartete Ausgabe: Excel-Tabellenblatt `custom sequence...` mit Durchlauf, Schritt, Gerät, Aktion, Parametern, Wert und Status. Die Backend-Funktion `run_frequency_sweep` erzeugt weiterhin `FrequencySweep...`, ist in der GUI aber nicht der primäre Bedienpfad.

Grenzen:

- Maximal `10000` Sweep-Punkte pro Ablauf.
- Große Diagramme werden für Excel gesampelt; die vollständigen Messdaten bleiben erhalten.
- Generatorfehler brechen den Ablauf ab und schalten RF aus.

### Automatischer Ablauf Mit Netzgerät

Netzgerät-Sweeps werden im Bereich `Automatischer Ablauf` über den Button `Freier Ablauf-Editor` erstellt. Der Ablauf ist für Tests wie `Netzteilspannung einstellen -> Messgerät messen -> nächsten Spannungspunkt` gedacht, z. B. Last-/Kennlinienmessungen oder DUT-Verhalten über Versorgungsspannung.

GUI-Test:

1. Netzgerät und Messgerät separat mit `IDN testen` prüfen.
2. Im Bereich `Automatischer Ablauf` den `Freier Ablauf-Editor` öffnen.
3. Netzgerät und Messgerät in der Geräteliste anlegen oder aus den gefundenen Geräten übernehmen.
4. Eine passende Vorlage wie `Netzgerät + Multimeter` oder `Netzgerät + Oszilloskop` einfügen.
5. Für den ersten Test kleine Punktzahl und sichere Grenzen wählen:
   - Netzteil Kanal: `1`
   - Netzteil Start: `0 V`
   - Stop: `2 V`
   - Schritt: `1 V`
   - Stromlimit: `0.1 A`
   - Max. V im Netzgerät-Bereich: z. B. `5`
   - Max. A im Netzgerät-Bereich: z. B. `0.5`
   - Wartezeit: `0.5`
   - Messart: `DMM` oder `Scope`
   - `Netzgerät am Ende aus`: aktiv
6. `Ablauf starten` ausführen.
7. Bei Bedarf `Stop` drücken. Das Netzgerät wird bei Stop oder Fehler sicherheitshalber über `OUTP:GEN 0` ausgeschaltet.

Verwendete Befehle je Spannungspunkt:

```text
INST:NSEL <channel>
VOLT <voltage>
CURR <current>
OUTP:SEL 1
OUTP:GEN 1
```

Am Ende bzw. bei Stop/Fehler:

```text
OUTP:GEN 0
```

Erwartete Ausgabe: Excel-Tabellenblatt `custom sequence...` mit Durchlauf, Schritt, Gerät, Aktion, Parametern, Wert und Status. Die Backend-Funktion `run_voltage_sweep` erzeugt weiterhin `VoltageSweep...`, ist in der GUI aber nicht der primäre Bedienpfad.

Grenzen:

- Maximal `10000` Sweep-Punkte pro Ablauf.
- Die Werte `Max. V` und `Max. A` aus dem Netzgerät-Bereich werden vor dem Start geprüft.
- Große Diagramme werden für Excel gesampelt; die vollständigen Messdaten bleiben erhalten.
- Netzgerätfehler brechen den Ablauf ab und schalten den Master-Ausgang aus.

### Oszilloskope

Erwartete Profile je nach Gerät: `keysight_infinivision_x`, `keysight_infinivision_6000`, `keysight_infinivision_7000`, `agilent_54600`, `tektronix_tds400`, `tektronix_tds30`, `tektronix_mdo`, `rs_rt_scope`, `lecroy_xstream`

GUI-Test:

1. `IDN testen` ausführen.
2. Bereich `Oszilloskop` muss sichtbar sein.
3. `Scope Messwert` mit `Vpp` und `CH1` testen.
4. `Waveform` mit einem Kanal testen.
5. `Screenshot` testen, wenn der Button sichtbar ist.
6. Optional `Getimtes Messen` mit kleiner Anzahl, z. B. Intervall `1`, Anzahl `3`, testen.

Typische Befehle je nach Profil:

```text
:MEASure...?
:WAVeform...?
:DISPlay:DATA?
MEASUrement:IMMed...
CURVe?
HARDCopy START
HCOPy:DATA?
SCREEN_DUMP
```

Erwartete Ausgabe: Messwerte in Excel, Waveform-CSV mit Diagramm, Screenshot-Artefakt neben der Excel-Datei.

### Multimeter

Erwartete Profile: `keysight_344_l44`, `keithley_2000`

GUI-Test:

1. `IDN testen` ausführen.
2. Bereich `Multimeter` muss sichtbar sein.
3. `DMM Messwert` ausführen.
4. Optional `Getimtes Messen` mit Intervall `1` und Anzahl `3` testen.

Verwendete Befehle:

```text
:READ?
```

Erwartete Ausgabe: Messwert bzw. Messreihe in Excel.

### Netzwerkanalysatoren E5071C/ZNB

Erwartete Profile: `keysight_e5071c`, `rs_znb`

GUI-Test:

1. `IDN testen` ausführen.
2. Bereich `Netzwerkanalysator` muss sichtbar sein.
3. S-Parameter-Ports und Format auswählen.
4. `S-Parameter exportieren` ausführen.
5. Optional `Screenshot` testen. Im freien Ablauf kann beim Schritt `Gerät: Screenshot erfassen` für ZNB zusätzlich `ZNB mit Infofenstern` aktiviert werden; dann werden Informationsfenster/Overlays über `HCOP:PAGE:WIND ALL` mit in denselben Screenshot aufgenommen. Es entstehen keine mehreren Screenshots.

Erwartete Ausgabe: Touchstone-/S-Parameter-Artefakt und Excel-Metadaten.

## Geräte-Testmatrix

Statuswerte:

- `getestet`: mit realem Gerät im aktuellen Python-Tool geprüft
- `VBA übernommen, getestet`: aus dem vorhandenen VBA-Projekt übernommen und im aktuellen Python-Tool mit realem Gerät geprüft
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
    Notizen:           34461A/34401A über :READ?; 34401A/HP/Agilent-Varianten fallen bewusst in dasselbe Profil. Beim 34461A über USB kann es vorkommen, dass das Gerät nach App-Start/Einschalten erst nach einmaligem USB-Abziehen und Wiedereinstecken von der VISA-Suche erkannt wird.

#### Keysight/Agilent InfiniiVision X-Series, DSOX2024A, MSOX3054T

    Profil-Key:        keysight_infinivision_x
    IDN-Erkennung:     DSOX oder MSOX
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG, Waveform ja
    Nicht unterstützt: DMM/Messwert, S-Parameter
    Status:            getestet
    Notizen:           Neue getimte Messung wurde mit Scope positiv getestet

#### Agilent/HP/Keysight 34970A/34972A

    Profil-Key:        keysight_34970a
    IDN-Erkennung:     34970A, 34972A, HP34970 oder HEWLETT-PACKARD 34970
    Funktionen:        Datenlogger-Kanäle messen, Messplan, direkte COM- oder VISA-ASRL-Anbindung
    Nicht unterstützt: DMM-READ?-Direktmessung, Screenshot, Waveform/Trace, S-Parameter
    Status:            getestet
    Notizen:           34970A mit seriellen Defaults 19200 8N1 getestet; USB-Seriell-Adapter benötigt passenden Windows-COM-Treiber

#### Konica Minolta CA-410

    Profil-Key:        konica_minolta_ca410
    IDN-Erkennung:     keine SCPI-IDN erwartet; manuell über `Als CA-410` auf COM/ASRL-Adresse setzen
    Funktionen:        Messwert über virtuellen COM-Port, Probe, Kalibrierkanal, Messmethode, Flicker-Methode, Messgeschwindigkeit, Farbmodus
    Nicht unterstützt: automatische IDN-Erkennung, Zero-Calibration-Auslösung, JEITA-Spektrum-Export, Trigger-Standby
    Status:            getestet
    Notizen:           CA-410-Messung mit realem Gerät erfolgreich getestet; Standardkommunikation 38400 7E2, RTS/CTS, CR-Abschluss

### Aus VBA Übernommen Und Getestet

#### Keysight/Agilent E5071C

    Profil-Key:        keysight_e5071c
    IDN-Erkennung:     E5071C
    Funktionen:        Screenshot PNG, S-Parameter ja
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Waveform/Trace
    Status:            VBA übernommen, getestet
    Notizen:           Screenshot und Touchstone/S-Parameter aus bestehender VBA-Logik übernommen und im Python-Tool geprüft

#### Rohde & Schwarz ZNB

    Profil-Key:        rs_znb
    IDN-Erkennung:     ZNB
    Funktionen:        Screenshot PNG, S-Parameter ja
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Waveform/Trace
    Status:            VBA übernommen, getestet
    Notizen:           Screenshot und Touchstone/S-Parameter aus bestehender VBA-Logik übernommen und im Python-Tool geprüft. Screenshot unterstützt aktives Fenster und im freien Ablauf zusätzlich die Anzeige inklusive Informationsfenstern/Overlays per `HCOP:PAGE:WIND ALL`.

#### Rohde & Schwarz FSW

    Profil-Key:        rs_fsw
    IDN-Erkennung:     FSW
    Funktionen:        Screenshot PNG
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Waveform/Trace, S-Parameter
    Status:            VBA übernommen, getestet
    Notizen:           Screenshot-Funktion aus bestehender VBA-Logik übernommen und im Python-Tool geprüft; Trace-Export aktuell nicht aktiviert

#### Keysight/Agilent/HP E740

    Profil-Key:        hp_e740
    IDN-Erkennung:     E740
    Funktionen:        Screenshot WMF, Trace CSV
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, S-Parameter
    Status:            VBA übernommen, getestet
    Notizen:           Spektrumanalysator-Export aus bestehender VBA-Logik übernommen und im Python-Tool geprüft

#### HP/Agilent 4395A

    Profil-Key:        hp_4395a
    IDN-Erkennung:     4395A
    Funktionen:        Waveform/Trace ja
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Screenshot, S-Parameter
    Status:            VBA übernommen, getestet
    Notizen:           Waveform-/Trace-Export aus bestehender VBA-Logik übernommen und im Python-Tool geprüft

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

#### HP 8591A

    Profil-Key:        hp_8591a
    IDN-Erkennung:     8591A
    Funktionen:        Trace A best-effort über TRA?, Screenshot/Hardcopy HP-GL über GETPLOT
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Älteres HP-IB/non-SCPI-Gerät; TRA?, GETPLOT und IDN-Verhalten mit realem Gerät prüfen. GETPLOT liefert voraussichtlich Plotterdaten statt Bitmap.

#### HP/Agilent E4402B ESA

    Profil-Key:        hp_agilent_e4402b
    IDN-Erkennung:     E4402B
    Funktionen:        Screenshot WMF, Trace CSV
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, S-Parameter
    Status:            commands from manual, untested
    Notizen:           ESA-family SCPI; nutzt zunächst E740-ähnliche MMEM-Trace-/Screenshot-Befehle, noch mit Laborgerät testen

#### Keysight/Agilent PXA/MXA/EXA/CXA, N90xx

    Profil-Key:        keysight_n90
    IDN-Erkennung:     N90
    Funktionen:        Screenshot PNG
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, Waveform/Trace, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Spektrumanalysator-Familie PXA/MXA/EXA/CXA; aktuell nur Screenshot-Profil aktiviert, Trace-Export noch nicht implementiert

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
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG
    Nicht unterstützt: DMM/Messwert, Waveform, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Best-effort aktiviert; Waveform erst nach Gerätetest/SCPI-Abgleich aktivieren

#### Tektronix MDO/MSO/DPO

    Profil-Key:        tektronix_mdo
    IDN-Erkennung:     TEKTRONIX und MSO4/MDO4/MDO3/DPO4
    Funktionen:        Scope-Messwert ja, getimtes Scope-Messen ja, Screenshot PNG
    Nicht unterstützt: DMM/Messwert, Waveform, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Best-effort aktiviert; Waveform erst nach Gerätetest/SCPI-Abgleich aktivieren

#### Rohde & Schwarz / Hameg HMS-X Spectrum Analyzer

    Profil-Key:        rs_hameg_hms
    IDN-Erkennung:     HAMEG oder ROHDE plus HMS
    Funktionen:        Screenshot BMP, Trace CSV
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, getimtes Messen, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Gegen hochgeladenes HMS-X-SCPI-Manual geprüft; echten Gerätetest nachtragen

#### Rohde & Schwarz / Hameg HMP4030/HMP4040/HMP2000

    Profil-Key:        rs_hmp_power_supply
    IDN-Erkennung:     HMP4030, HMP4040, HMP2020 oder HMP2030
    Funktionen:        Kanal wählen, Spannung/Stromlimit lesen und setzen, Istspannung/Iststrom lesen, Ausgang je Kanal schalten
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, Screenshot, Waveform/Trace, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Nutzt HMP-SCPI `INST:NSEL`, `VOLT`, `CURR`, `MEAS:VOLT?`, `MEAS:CURR?`, `OUTP:SEL`, `OUTP:GEN`; HMP4030 hat 3 Kanäle, GUI erlaubt wegen HMP4040 bis 4 Kanäle

#### Rohde & Schwarz SMGU/SMHU

    Profil-Key:        rs_smg_legacy
    IDN-Erkennung:     ROHDE plus SMGU oder SMHU
    Funktionen:        Frequenz/Pegel/RF-Ausgang lesen und setzen
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, Screenshot, Waveform/Trace, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Ältere Signalgeneratoren; nutzt Manual-Beispiele `RF <freq>`, `RF?`, `LEVEL:RF <level>`, `LEVEL:RF?`, `LEVEL:RF:ON/OFF`; Rückmeldung vom echten Gerät prüfen

#### Rohde & Schwarz SME/SMT/SMIQ

    Profil-Key:        rs_sme_smt_smiq
    IDN-Erkennung:     ROHDE plus SME, SMT oder SMIQ
    Funktionen:        Frequenz/Pegel/RF-Ausgang lesen und setzen
    Nicht unterstützt: DMM/Messwert, Scope-Messwert, Screenshot, Waveform/Trace, S-Parameter
    Status:            commands from manual, untested
    Notizen:           Signalgeneratoren mit SCPI/IEEE-488.2; Manual-Langformen `[:SOURce]:FREQuency[:CW|:FIXed]`, `[:SOURce]:POWer[:LEVel][:IMMediate][:AMPLitude]`, `:OUTPut[:STATe]`, Kurzformen im Tool genutzt

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

### PicoSDK-Geräte

#### Pico Technology PicoScope 2206BMSO/2406B

    Profil-Key:        picoscope
    IDN-Erkennung:     keine VISA-IDN; Adresse `PICO2000A::AUTO` oder `PICO2000A::SERIAL::<seriennummer>`
    Funktionen:        analoge Block-Aufnahme ja; digitale MSO-Aufnahme beim 2206BMSO
    Nicht unterstützt: SCPI/VISA-IDN, komplexe Trigger, Streaming; digitale Kanäle beim 2406B
    Status:            PicoSDK-2000A vorbereitet, mit Hardware noch zu testen
    Notizen:           Zielgeräte PicoScope 2206BMSO und 2406B; PicoSDK 64-bit/ps2000a auf Ziel-PC erforderlich. Das Programm liest die PicoSDK-Variant-Info: 2206BMSO wird auf Analog A/B plus Digital D0-D15 beschränkt, 2406B auf Analog A-D ohne Digitalaufnahme.

### Saleae-Geräte

#### Saleae Logic Analyzer mit Logic 2 Automation

    Profil-Key:        saleae_logic2
    IDN-Erkennung:     keine VISA-IDN; Adresse `SALEAE::LOCAL`
    Funktionen:        digitale Aufnahme, UART/I2C/SPI/CAN-Analyzer-Export über Logic 2 Automation
    Nicht unterstützt: analoge Saleae-Kanäle, SCPI/VISA-IDN
    Status:            vorbereitet, mit Hardware noch zu testen
    Notizen:           Benötigt installierte Saleae Logic 2, aktivierte Automation auf Port 10430 und Python-Paket `logic2-automation` bzw. eine damit gebaute EXE

Für neue Rückmeldungen reicht es, den Status und die Notizen im jeweiligen Geräteblock zu aktualisieren. Sinnvoll sind kurze Einträge wie `getestet: IDN, Messwert, Screenshot ok; Waveform Fehler ...`.

## Hinweise

Für echte Kommunikationstests müssen die passenden Gerätetreiber/VISA-Runtimes installiert und die Messgeräte angeschlossen sein. Die hardware-unabhängigen Tests prüfen die Python-Logik ohne reale Geräte.

Hardware-unabhängige Tests liegen unter `tests/` und nutzen Fake-Instrumente. Damit werden Profil-Erkennung, wichtige SCPI-Befehlsfolgen, Screenshot-Binärdaten-Normalisierung, Excel-Export, Sequenzen, serielle Logs/Kommandos, SSH, PicoScope-, Saleae-, 34970A-, CA-410- und Sweep-Sicherheitslogik geprüft, ohne echte Messgeräte anzusprechen.
