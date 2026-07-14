# Installation fuer Kollegen

Diese Anleitung ist fuer Ziel-PCs gedacht, auf denen die fertige EXE genutzt wird. Die EXE enthaelt die Anwendung, aber keine Windows-Treiber und keine Hersteller-Runtimes.

## Kurzfassung

1. Anwendung entpacken und noch nicht starten.
2. Passende Treiber aus dem Dependencies-Paket installieren.
3. PC neu starten, wenn ein Installer das verlangt.
4. Messgeraet anschliessen und einschalten.
5. `MeasurementDevicesCommunicationLibrary.exe` starten.
6. In der App `Setup pruefen` ausfuehren.
7. Fehlende Treiber oder Runtimes aus dem Diagnosefenster installieren.
8. Danach `Geraete suchen` ausfuehren.
9. Passendes Geraet auswaehlen und `IDN testen` druecken.

## Was muss ich installieren?

| Ich moechte nutzen | Installieren |
| --- | --- |
| Normales Messgeraet per USB, LAN oder GPIB | `1_Immer_zuerst_VISA` |
| Keysight/Agilent-Geraet, besonders wenn es nicht gefunden wird | `2_Falls_Keysight_Agilent` |
| R&S/Hameg HMS/HMP mit USB-Interface | `1_Immer_zuerst_VISA` und danach `3_Falls_Hameg_RS_USB` |
| PicoScope 2206BMSO oder 2406B | `4_Falls_PicoScope` |
| Saleae Logic Analyzer | `5_Falls_Saleae` |
| Konica Minolta CA-410 per USB | Konica-Minolta USB-Treiber fuer den virtuellen COM-Port |
| USB-RS232-Adapter oder direkter COM-Port | `6_Falls_USB_RS232_COM`, falls Windows keinen COM-Port anzeigt |
| Alte GPIB-Geraete ueber USB-GPIB-Adapter | `1_Immer_zuerst_VISA` und danach `7_Falls_USB_GPIB` oder den Treiber des Adapter-Herstellers |

## Unterstuetzte Geraete konkret

Die folgende Tabelle deckt die in der Anwendung hinterlegten Geraeteprofile ab. Wenn ein Geraet nicht exakt genannt ist, aber zur gleichen Familie gehoert, gilt die gleiche Zeile.

| Geraet / Familie | Installieren | Hinweis |
| --- | --- | --- |
| Keysight/Agilent 344xx/L44xx, z. B. 34461A, 34401A | `1_Immer_zuerst_VISA`; bei Keysight-Problemen `2_Falls_Keysight_Agilent` | DMM ueber USB/LAN/GPIB/VISA. |
| Keysight/Agilent InfiniiVision X-Series, 6000, 7000, z. B. DSOX/MSOX/MSO6/DSO6/MSO7/DSO7 | `1_Immer_zuerst_VISA`; bei Keysight-Problemen `2_Falls_Keysight_Agilent` | Oszilloskope ueber VISA. |
| HP/Agilent 54600/54620, z. B. 54622D | `1_Immer_zuerst_VISA`; je nach Anschluss zusaetzlich `7_Falls_USB_GPIB` oder `6_Falls_USB_RS232_COM` | Aelteres Scope, haeufig GPIB oder RS232. |
| Keysight/Agilent E5071C | `1_Immer_zuerst_VISA`; bei Keysight-Problemen `2_Falls_Keysight_Agilent` | Netzwerkanalysator ueber VISA. |
| Rohde & Schwarz ZNB | `1_Immer_zuerst_VISA` | Netzwerkanalysator ueber VISA. |
| Rohde & Schwarz FSW | `1_Immer_zuerst_VISA` | Spektrumanalysator ueber VISA. |
| Keysight/Agilent/HP E740, E4402B ESA, PXA/MXA/EXA/CXA N90xx | `1_Immer_zuerst_VISA`; bei Keysight-Problemen `2_Falls_Keysight_Agilent` | Spektrumanalysatoren ueber VISA. |
| HP/Agilent 4395A | `1_Immer_zuerst_VISA`; je nach Anschluss zusaetzlich `7_Falls_USB_GPIB` | Aelterer Netzwerk-/Spektrumanalysator. |
| HP 8591A | `1_Immer_zuerst_VISA` und passender GPIB-Treiber, meist `7_Falls_USB_GPIB` | Aelteres HP-IB/GPIB-Geraet. |
| Keithley 2000 | `1_Immer_zuerst_VISA`; je nach Anschluss `7_Falls_USB_GPIB` oder `6_Falls_USB_RS232_COM` | DMM ueber GPIB/RS232/VISA. |
| Tektronix TDS400/TDS420A, TDS3000, MDO/MSO/DPO | `1_Immer_zuerst_VISA`; je nach Anschluss `7_Falls_USB_GPIB` | Tektronix-Scopes ueber VISA. |
| Rohde & Schwarz / Hameg HMS-X | `1_Immer_zuerst_VISA`; bei USB-Interface `3_Falls_Hameg_RS_USB` | Spektrumanalysator. |
| Rohde & Schwarz / Hameg HMP4030/HMP4040/HMP2020/HMP2030 | `1_Immer_zuerst_VISA`; bei USB-Interface `3_Falls_Hameg_RS_USB` | Netzgeraete; in der App bevorzugt `ASRL...::INSTR` statt direktem `COM`. |
| Rohde & Schwarz SME/SMT/SMIQ und SMGU/SMHU | `1_Immer_zuerst_VISA`; je nach Anschluss `7_Falls_USB_GPIB` | Signalgeneratoren, oft GPIB/VISA. |
| Rohde & Schwarz RT-Series, RTB/RTA/RTM/RTE/RTO/RTP | `1_Immer_zuerst_VISA` | Oszilloskope ueber VISA. |
| Teledyne LeCroy WavePro/WaveRunner/SDA/Zi | `1_Immer_zuerst_VISA` | Meist LAN/VISA. |
| Agilent/HP/Keysight 34970A/34972A | `1_Immer_zuerst_VISA` fuer `ASRL...::INSTR`; bei USB-Seriell `6_Falls_USB_RS232_COM` | Direkter `COM`-Betrieb geht auch ohne VISA, braucht aber COM-Treiber. |
| Konica Minolta CA-410 | Konica-Minolta USB-Treiber fuer virtuellen COM-Port; bei echter RS-232-Verbindung ggf. `6_Falls_USB_RS232_COM` | In der App COM-Port auswaehlen und `Als CA-410` druecken. Standard: `38400`, `7E2`, RTS/CTS, Abschluss `CR`. |
| PicoScope 2206BMSO/2406B | `4_Falls_PicoScope` | PicoSDK 64-bit erforderlich. |
| Saleae Logic Analyzer | `5_Falls_Saleae` | Logic 2 muss laufen, Automation muss aktiv sein. |

## Reihenfolge

1. Zuerst immer eine VISA Runtime installieren, wenn das Geraet ueber `USB...`, `TCPIP...`, `GPIB...` oder `ASRL...` angesprochen wird.
2. Danach nur die Zusatztreiber installieren, die zum konkreten Geraet oder Adapter passen.
3. Nicht wahllos alle Installer installieren. Besonders VISA-Pakete verschiedener Hersteller koennen sich gegenseitig beeinflussen.

## Hinweise zu einzelnen Geraeten

### Keysight/Agilent

Wenn ein Keysight-/Agilent-Geraet nicht gefunden wird, die Keysight IO Libraries installieren und im Keysight Connection Expert pruefen, ob das Geraet sichtbar ist.

### R&S/Hameg

Fuer viele Geraete reicht R&S VISA. Bei HMS-/HMP-Geraeten mit altem USB-Interface kann zusaetzlich der HO720/HO730- oder HO732-Treiber noetig sein.

### PicoScope

PicoScope funktioniert nur mit installiertem PicoSDK 64-bit. Ohne PicoSDK startet die App, PicoScope-Schritte melden aber einen Fehler.

### Saleae

Saleae Logic 2 muss installiert sein und laufen. Die Automation-Schnittstelle muss aktiviert sein. Falls die App Saleae nicht erreicht, Logic 2 mit `Logic.exe --automation` starten.

### COM-Port / RS232

Im Windows-Geraetemanager muss ein COM-Port sichtbar sein, z. B. `COM3`. Wenn kein COM-Port erscheint, fehlt der USB-Seriell-Treiber oder der falsche Adaptertreiber ist installiert.

## Wenn das Geraet nicht gefunden wird

1. Kabel und Stromversorgung pruefen.
2. Geraet einmal neu einschalten.
3. In der App `Setup pruefen` ausfuehren und die Empfehlungen lesen.
4. Windows-Geraetemanager pruefen: unbekanntes Geraet oder fehlender COM-Port bedeutet Treiberproblem.
5. Bei VISA-Geraeten mit Keysight Connection Expert oder R&S VISA Tester pruefen, ob das Geraet dort sichtbar ist.
6. In der App erneut `Geraete suchen` und danach `IDN testen` ausfuehren.

## Was prueft `Setup pruefen`?

- VISA Runtime nutzbar ja/nein
- Gefundene VISA-Geraete
- Gefundene COM-Ports
- Moegliche CA-410-COM-Ports anhand der Windows-Portbeschreibung
- PicoSDK 2000A fuer PicoScope vorhanden ja/nein
- Gefundene PicoScope-Geraete
- Saleae Python-Paket vorhanden ja/nein
- Saleae Logic-2-Automation auf Port 10430 erreichbar ja/nein
- Gefundene Saleae-Geraete
- Konkrete Empfehlungen fuer fehlende Treiber oder Runtimes
- Hinweis: CA-410 liefert normalerweise keine SCPI-IDN. COM-Port auswaehlen und `Als CA-410` druecken.
