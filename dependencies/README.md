# Lokale Runtime-Abhängigkeiten

Dieser Ordner ist für externe Installer, Treiber und SDKs gedacht, die auf Zielrechnern zusätzlich zur EXE benötigt werden. Das Release-Skript kopiert den kompletten Ordner automatisch in die EXE- und Python-Source-Verteilerordner, wenn er lokal vorhanden ist.

Empfohlene Ablage:

- `dependencies/`
- `dependencies/RS_VISA_Setup_Win_<version>.exe`
- `dependencies/PicoSDK_x64_<version>.exe`
- `dependencies/Logic-<version>-windows-x64.exe`
- `dependencies/HO720-HO730-Interface-Driver-<version>.zip`
- `dependencies/HO732-USB-Driver-<version>.zip`
- `dependencies/CDM<version>_Setup.zip`
- `dependencies/Treiber USB-GPIB.7z`
- `dependencies/README.md`

Hinweise:

- Die EXE enthält Python-Code und Python-Pakete, aber keine Systemtreiber. VISA, PicoSDK und Saleae Logic 2 müssen auf dem Ziel-PC installiert werden.
- Saleae benötigt zusätzlich die aktivierte Logic-2-Automation-Schnittstelle, z. B. Start von Logic 2 mit `Logic.exe --automation`. Python-Installationen benötigen außerdem `py -m pip install -e ".[saleae]"`; EXE-Releases enthalten `logic2-automation`, wenn sie mit dem normalen Build-Skript ohne `-SkipInstall` gebaut wurden.
- IVI-/VXIplug&play-Instrumententreiber sind für diese App normalerweise nicht nötig. Die App nutzt PyVISA/SCPI direkt und bindet keine herstellerspezifischen IVI-/VXI-PnP-DLLs ein.

## Zuordnung der Installer

### Allgemeine Kommunikation

| Installer | Zweck | Benötigt für |
| --- | --- | --- |
| `RS_VISA_Setup_Win_7_2_3.exe` | R&S VISA Runtime | Allgemeine VISA-/SCPI-Kommunikation über `USB...::INSTR`, `GPIB...::INSTR`, `TCPIP...::INSTR` und `ASRL...::INSTR`. Wichtig für die meisten Messgeräte. |

### Geräte- und SDK-spezifisch

| Installer | Zweck | Benötigt für |
| --- | --- | --- |
| `PicoSDK_x64_11.1.0.479.exe` | PicoSDK 64-bit mit `ps2000a`-Treiber | PicoScope 2206BMSO und PicoScope 2406B über `PICO2000A::AUTO` oder `PICO2000A::SERIAL::<seriennummer>`. |
| `Logic-2.4.44-windows-x64.exe` | Saleae Logic 2 | Saleae Logic Analyzer über `SALEAE::LOCAL`. Logic 2 muss laufen und die Automation-Schnittstelle muss aktiv sein. |

### Schnittstellen- und Adaptertreiber

| Installer | Zweck | Benötigt für |
| --- | --- | --- |
| `HO720-HO730-Interface-Driver-2_12_28.zip` | R&S/Hameg HO720/HO730 Interface-Treiber | Hameg/R&S-Geräte mit HO720/HO730-Schnittstelle, z. B. HMS-/HMP-Geräte je nach eingebautem Interface. |
| `HO732-USB-Driver-1_0.zip` | R&S/Hameg HO732 USB-Treiber | Hameg/R&S-Geräte mit HO732-USB-Schnittstelle. |
| `CDM2123620_Setup.zip` | FTDI VCP-/USB-Seriell-Treiber | USB-RS232-/USB-Seriell-Adapter mit FTDI-Chip, z. B. für direkte `COMx`-Verbindungen und serielle Logs. |
| `Treiber USB-GPIB.7z` | USB-GPIB-Adapter-Treiber | GPIB-Anbindung älterer Messgeräte, falls der konkrete USB-GPIB-Adapter diesen Treiber benötigt. |

## Installationshinweise

- Für reine LAN-Geräte reicht normalerweise die VISA-Runtime; zusätzliche USB-Treiber sind dann nicht nötig.
- Für USBTMC-Geräte reicht oft die VISA-Runtime, sofern Windows das Gerät als VISA-Ressource erkennt.
- Für HMP/HMS-Geräte zuerst R&S VISA installieren, danach bei Bedarf den passenden HO720/HO730- oder HO732-Treiber.
- Für ältere GPIB-Geräte muss der Treiber zum tatsächlich verwendeten GPIB-Adapter passen. Falls ein anderer Adapter verwendet wird, z. B. NI oder Keysight, ist dessen Herstellerpaket erforderlich.
- Für direkte COM-Verbindungen muss der passende USB-Seriell-Treiber installiert sein; FTDI hilft nur bei Adaptern mit FTDI-Chip.
