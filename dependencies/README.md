# Lokale Runtime-Abhaengigkeiten

Dieser Ordner ist fuer externe Installer, Treiber und SDKs gedacht, die auf Zielrechnern zusaetzlich zur EXE benoetigt werden. Die EXE enthaelt Python-Code und Python-Pakete, aber keine Systemtreiber.

Fuer Kollegen gibt es die kurze Anleitung `INSTALLATION_KOLLEGEN.md`. Diese README ist die technische Zuordnung der Installer.

## Wichtig fuer Ziel-PCs

- Nicht wahllos alle Installer installieren. Nur die Pakete installieren, die zum Messgeraet und Anschluss passen.
- Fuer normale Messgeraete ueber `USB...`, `TCPIP...`, `GPIB...` oder `ASRL...` wird eine VISA Runtime benoetigt.
- IVI-/VXIplug&play-Instrumententreiber sind fuer diese App normalerweise nicht noetig. Die App nutzt PyVISA/SCPI direkt und bindet keine herstellerspezifischen IVI-/VXI-PnP-DLLs ein.
- Saleae benoetigt zusaetzlich die aktivierte Logic-2-Automation-Schnittstelle, z. B. Start von Logic 2 mit `Logic.exe --automation`. Python-Installationen benoetigen ausserdem `py -m pip install -e ".[saleae]"`; EXE-Releases enthalten `logic2-automation`, wenn sie mit dem normalen Build-Skript ohne `-SkipInstall` gebaut wurden.

## Ordner im Dependencies-Release

Das Release-Skript sortiert die Dateien fuer Kollegen in nummerierte Ordner:

| Ordner | Inhalt | Nutzen |
| --- | --- | --- |
| `1_Immer_zuerst_VISA` | R&S VISA Runtime | Basis fuer die meisten Messgeraete ueber USB, LAN, GPIB oder ASRL. |
| `2_Falls_Keysight_Agilent` | Keysight IO Libraries Suite | Keysight-/Agilent-Geraete, Connection Expert, alternative VISA Runtime. |
| `3_Falls_Hameg_RS_USB` | HO720/HO730 und HO732 Treiber | Hameg/R&S-Geraete mit diesen USB-Interfaces. |
| `4_Falls_PicoScope` | PicoSDK 64-bit | PicoScope 2206BMSO und PicoScope 2406B. |
| `5_Falls_Saleae` | Saleae Logic 2 | Saleae Logic Analyzer ueber `SALEAE::LOCAL`. |
| `6_Falls_USB_RS232_COM` | FTDI VCP-/USB-Seriell-Treiber | USB-RS232-/COM-Port-Verbindungen mit FTDI-Chip. |
| `7_Falls_USB_GPIB` | USB-GPIB-Adaptertreiber | Aeltere GPIB-Geraete, falls dieser konkrete Adapter verwendet wird. |
| `8_Falls_Konica_Minolta_CA410` | CA-410 Kommunikation, optional USB-Treiber | Konica Minolta CA-410 ueber virtuellen COM-Port. |
| `9_Sonstiges` | Nicht automatisch zugeordnete Dateien | Manuell pruefen. |

## Zuordnung nach Geraet und Anschluss

| Geraet / Anschluss | Installieren | Hinweis |
| --- | --- | --- |
| Normales Messgeraet per USB, LAN oder GPIB | `RS_VISA_Setup_Win_7_2_3.exe` | Reicht fuer viele SCPI-Geraete. |
| Keysight/Agilent per USB, LAN oder GPIB | `IOLibrariesSuite-21.3.293-windows-x64.exe` | Empfohlen, wenn das Geraet im Keysight Connection Expert sichtbar sein soll oder mit R&S VISA nicht gefunden wird. |
| R&S/Hameg HMS/HMP mit HO720/HO730 | `RS_VISA_Setup_Win_7_2_3.exe` und `HO720-HO730-Interface-Driver-2_12_28.zip` | Erst VISA, dann Interface-Treiber. |
| R&S/Hameg mit HO732 USB | `RS_VISA_Setup_Win_7_2_3.exe` und `HO732-USB-Driver-1_0.zip` | Erst VISA, dann USB-Treiber. |
| PicoScope 2206BMSO/2406B | `PicoSDK_x64_11.1.0.479.exe` | Ohne PicoSDK startet die App, aber PicoScope-Schritte funktionieren nicht. |
| Saleae Logic Analyzer | `Logic-2.4.44-windows-x64.exe` | Logic 2 muss laufen und Automation muss aktiv sein. |
| Konica Minolta CA-410 per USB | Konica-Minolta USB-Treiber fuer virtuellen COM-Port | Treiber/Software muss ueber Konica Minolta Download/Support bezogen werden; falls lokal abgelegt, wird es in `8_Falls_Konica_Minolta_CA410` sortiert. |
| Direkte COM-Verbindung / USB-RS232 | `CDM2123620_Setup.zip`, falls FTDI-Adapter | Nur passend fuer FTDI-Chips. Andere Adapter brauchen ihren eigenen Treiber. |
| Aeltere GPIB-Geraete ueber USB-GPIB | `Treiber USB-GPIB.7z` oder Treiber des Adapter-Herstellers | Der Treiber muss zum konkret verwendeten GPIB-Adapter passen. |

## Abdeckung der unterstuetzten Geraeteprofile

Diese Matrix ist aus den in der Anwendung hinterlegten Geraeteprofilen abgeleitet. Sie soll absichern, dass fuer jedes unterstuetzte Profil eine Runtime-/Treiberempfehlung vorhanden ist.

| Profil-Key | Geraet / Familie | Basisinstallation | Zusatz bei Bedarf |
| --- | --- | --- | --- |
| `keysight_344_l44` | Keysight/Agilent 344xx/L44xx, z. B. 34461A, 34401A | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe`, wenn Keysight-Geraet nicht gefunden wird; GPIB-/COM-Adaptertreiber je nach Anschluss. |
| `keysight_infinivision_x` | Keysight/Agilent InfiniiVision X-Series, DSOX/MSOX | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe` fuer Keysight Connection Expert oder Erkennungsprobleme. |
| `keysight_infinivision_6000` | Keysight/Agilent InfiniiVision 6000, MSO6/DSO6 | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe` fuer Keysight Connection Expert oder Erkennungsprobleme. |
| `keysight_infinivision_7000` | Keysight/Agilent InfiniiVision 7000, MSO7/DSO7 | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe` fuer Keysight Connection Expert oder Erkennungsprobleme. |
| `agilent_54600` | HP/Agilent 54600/54620, z. B. 54622D | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB- oder USB-RS232-Adaptertreiber passend zum Anschluss. |
| `keysight_e5071c` | Keysight/Agilent E5071C | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe` fuer Keysight Connection Expert oder Erkennungsprobleme. |
| `rs_znb` | Rohde & Schwarz ZNB | `RS_VISA_Setup_Win_7_2_3.exe` | Normalerweise kein Zusatztreiber bei LAN/USBTMC. |
| `rs_fsw` | Rohde & Schwarz FSW | `RS_VISA_Setup_Win_7_2_3.exe` | Normalerweise kein Zusatztreiber bei LAN/USBTMC. |
| `hp_e740` | Keysight/Agilent/HP E740 | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe` oder GPIB-Adaptertreiber je nach Anschluss. |
| `hp_agilent_e4402b` | HP/Agilent E4402B ESA | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe` oder GPIB-Adaptertreiber je nach Anschluss. |
| `keysight_n90` | Keysight/Agilent PXA/MXA/EXA/CXA, N90xx | `RS_VISA_Setup_Win_7_2_3.exe` | `IOLibrariesSuite-21.3.293-windows-x64.exe` fuer Keysight Connection Expert oder Erkennungsprobleme. |
| `hp_4395a` | HP/Agilent 4395A | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB-Adaptertreiber passend zum verwendeten Adapter. |
| `hp_8591a` | HP 8591A | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB-Adaptertreiber passend zum verwendeten Adapter; bei NI/Keysight-Adaptern Herstellerpaket verwenden. |
| `keithley_2000` | Keithley 2000 | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB- oder USB-RS232-Adaptertreiber passend zum Anschluss. |
| `tektronix_tds400` | Tektronix TDS400/TDS420A | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB-Adaptertreiber bei GPIB-Anbindung. |
| `tektronix_tds30` | Tektronix TDS3000 | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB-Adaptertreiber bei GPIB-Anbindung. |
| `tektronix_mdo` | Tektronix MDO/MSO/DPO | `RS_VISA_Setup_Win_7_2_3.exe` | Normalerweise kein Zusatztreiber bei LAN/USBTMC; GPIB-Adaptertreiber bei GPIB. |
| `rs_hameg_hms` | Rohde & Schwarz / Hameg HMS-X | `RS_VISA_Setup_Win_7_2_3.exe` | `HO720-HO730-Interface-Driver-2_12_28.zip` oder `HO732-USB-Driver-1_0.zip`, falls dieses USB-Interface genutzt wird. |
| `rs_hmp_power_supply` | Rohde & Schwarz / Hameg HMP4030/HMP4040/HMP2020/HMP2030 | `RS_VISA_Setup_Win_7_2_3.exe` | `HO720-HO730-Interface-Driver-2_12_28.zip` oder `HO732-USB-Driver-1_0.zip`, falls dieses USB-Interface genutzt wird. |
| `rs_smg_legacy` | Rohde & Schwarz SMGU/SMHU | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB-Adaptertreiber passend zum verwendeten Adapter. |
| `rs_sme_smt_smiq` | Rohde & Schwarz SME/SMT/SMIQ | `RS_VISA_Setup_Win_7_2_3.exe` | GPIB-Adaptertreiber passend zum verwendeten Adapter. |
| `rs_rt_scope` | Rohde & Schwarz RT-Series, RTB/RTA/RTM/RTE/RTO/RTP | `RS_VISA_Setup_Win_7_2_3.exe` | Normalerweise kein Zusatztreiber bei LAN/USBTMC. |
| `lecroy_xstream` | Teledyne LeCroy WavePro/WaveRunner/SDA/Zi | `RS_VISA_Setup_Win_7_2_3.exe` | Normalerweise kein Zusatztreiber bei LAN/VISA. |
| `keysight_34970a` | Agilent/HP/Keysight 34970A/34972A | `RS_VISA_Setup_Win_7_2_3.exe`, wenn `ASRL...::INSTR` verwendet wird | `CDM2123620_Setup.zip` oder anderer USB-Seriell-Treiber, wenn ein USB-RS232-Adapter verwendet wird. |
| `konica_minolta_ca410` | Konica Minolta CA-410 | Kein VISA erforderlich bei direktem virtuellen COM-Port | Konica-Minolta USB-Treiber fuer den virtuellen COM-Port, laut Hersteller `KMMIUSB.INF`/`KMMIUSB.CAT`; bei RS-232 kein spezieller Treiber, aber ggf. USB-RS232-Adaptertreiber. |
| `picoscope` | PicoScope 2206BMSO/2406B | `PicoSDK_x64_11.1.0.479.exe` | Keine VISA Runtime fuer PicoSDK-Betrieb erforderlich. |
| `saleae_logic2` | Saleae Logic Analyzer | `Logic-2.4.44-windows-x64.exe` | Logic 2 Automation aktivieren; EXE muss mit `logic2-automation` gebaut sein. |

## Empfohlene Ablage im Entwicklungsordner

- `dependencies/`
- `dependencies/RS_VISA_Setup_Win_<version>.exe`
- `dependencies/IOLibrariesSuite-<version>-windows-x64.exe`
- `dependencies/PicoSDK_x64_<version>.exe`
- `dependencies/Logic-<version>-windows-x64.exe`
- `dependencies/HO720-HO730-Interface-Driver-<version>.zip`
- `dependencies/HO732-USB-Driver-<version>.zip`
- `dependencies/CDM<version>_Setup.zip`
- `dependencies/Treiber USB-GPIB.7z`
- `dependencies/README.md`
- `dependencies/INSTALLATION_KOLLEGEN.md`

## Installationshinweise

- Fuer reine LAN-Geraete reicht normalerweise eine VISA Runtime; zusaetzliche USB-Treiber sind dann nicht noetig.
- Fuer USBTMC-Geraete reicht oft die VISA Runtime, sofern Windows das Geraet als VISA-Ressource erkennt.
- Fuer HMP/HMS-Geraete zuerst R&S VISA installieren, danach bei Bedarf den passenden HO720/HO730- oder HO732-Treiber.
- Fuer aeltere GPIB-Geraete muss der Treiber zum tatsaechlich verwendeten GPIB-Adapter passen. Falls ein anderer Adapter verwendet wird, z. B. NI oder Keysight, ist dessen Herstellerpaket erforderlich.
- Fuer direkte COM-Verbindungen muss der passende USB-Seriell-Treiber installiert sein; FTDI hilft nur bei Adaptern mit FTDI-Chip.
