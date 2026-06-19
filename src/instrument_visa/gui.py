from __future__ import annotations

import csv
import json
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from io import StringIO
from pathlib import Path
from time import monotonic
from tkinter import filedialog, messagebox, ttk

from .acquisition import AcquisitionResult, capture_screenshot, capture_sparameters, capture_waveform, read_scope_measurement, read_value
from .config import SParameterConfig
from .excel_export import append_result
from .logging_utils import setup_logging
from .profiles import UNKNOWN_PROFILE, DeviceProfile, detect_profile
from .visa_client import VisaInstrument, list_resources


DEFAULT_ADDRESS = "USB0::0x0957::0x1796::MY58104189::0::INSTR"
SETTINGS_PATH = Path("gui_settings.json")


class InstrumentVisaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Instrument VISA Export")

        self.settings = self._load_settings()
        self.geometry(self.settings.get("window_geometry", "1040x820"))
        self.minsize(940, 760)
        self.saved_devices = self._load_saved_devices()
        self.last_found_resources: list[str] = []
        self.resource_display_map: dict[str, str] = {}
        self.logger = setup_logging()

        self.address_var = tk.StringVar(value=self.settings.get("address", DEFAULT_ADDRESS))
        self.resource_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value=self.settings.get("output", str(Path("results.xlsx"))))
        self.device_type_var = tk.StringVar(value="Nicht erkannt")
        self.profile_var = tk.StringVar(value="Profil: nicht erkannt")
        self.measurement_var = tk.StringVar(value=self.settings.get("measurement", "Vpp"))
        self.channel_var = tk.IntVar(value=int(self.settings.get("channel", 1)))
        self.timed_interval_var = tk.StringVar(value=str(self.settings.get("timed_interval", "1")))
        self.timed_count_var = tk.StringVar(value=str(self.settings.get("timed_count", "10")))
        self.point_mode_var = tk.StringVar(value=self.settings.get("point_mode", "RAW"))
        waveform_channels = set(self.settings.get("waveform_channels", [1, 2, 3, 4]))
        self.waveform_channel_vars = {channel: tk.BooleanVar(value=channel in waveform_channels) for channel in range(1, 5)}
        self.sparameter_format_var = tk.StringVar(value=self.settings.get("sparameter_format", "AUTO"))
        sparameter_ports = set(self.settings.get("sparameter_ports", [1, 2]))
        self.sparameter_port_vars = {port: tk.BooleanVar(value=port in sparameter_ports) for port in range(1, 5)}
        self.status_var = tk.StringVar(value="Bereit")
        self._scope_widgets: list[tk.Widget] = []
        self._dmm_widgets: list[tk.Widget] = []
        self._vna_widgets: list[tk.Widget] = []
        self._screenshot_widgets: list[tk.Widget] = []
        self._timed_widgets: list[tk.Widget] = []
        self._timed_dmm_widgets: list[tk.Widget] = []
        self._timed_scope_widgets: list[tk.Widget] = []
        self._timed_stop_widgets: list[tk.Widget] = []
        self.timed_stop_event = threading.Event()
        self.timed_running = False
        self.current_profile: DeviceProfile = UNKNOWN_PROFILE
        self._messages: queue.Queue[tuple[str, object]] = queue.Queue()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self._process_messages)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        connection = ttk.LabelFrame(self, text="Verbindung")
        connection.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        connection.columnconfigure(1, weight=1)

        ttk.Label(connection, text="Gefundene Geräte").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.resource_combo = ttk.Combobox(connection, textvariable=self.resource_var, state="readonly")
        self.resource_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        self.resource_combo.bind("<<ComboboxSelected>>", self.select_device)
        ttk.Button(connection, text="Geräte suchen", command=self.search_devices).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(connection, text="IDN testen", command=self.test_idn).grid(row=0, column=3, padx=8, pady=8)
        ttk.Label(connection, text="VISA-Adresse").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        address_entry = ttk.Entry(connection, textvariable=self.address_var)
        address_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))
        address_entry.bind("<FocusOut>", self.apply_saved_profile)
        address_entry.bind("<Return>", self.apply_saved_profile)
        ttk.Label(connection, text="Gerätetyp").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Label(connection, textvariable=self.device_type_var).grid(row=2, column=1, sticky="w", padx=8, pady=(0, 8))
        ttk.Label(connection, textvariable=self.profile_var).grid(row=2, column=2, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        export = ttk.LabelFrame(self, text="Export")
        export.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        export.columnconfigure(1, weight=1)

        ttk.Label(export, text="Excel-Datei").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(export, textvariable=self.output_var).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(export, text="Auswählen", command=self.choose_output).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(export, text="Excel öffnen", command=self.open_excel).grid(row=0, column=3, padx=8, pady=8)
        ttk.Button(export, text="Ordner öffnen", command=self.open_output_folder).grid(row=0, column=4, padx=8, pady=8)

        measurement_area = ttk.Frame(self)
        measurement_area.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        measurement_area.columnconfigure(0, weight=1)
        measurement_area.columnconfigure(1, weight=1)

        scope = ttk.LabelFrame(measurement_area, text="Oszilloskop")
        scope.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        scope_measurement = ttk.Frame(scope)
        scope_measurement.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        scope_value_button = ttk.Button(scope_measurement, text="Scope Messwert", command=self.read_scope_measurement)
        scope_value_button.pack(side="left", padx=(0, 8))
        ttk.Label(scope_measurement, text="Messung").pack(side="left", padx=(0, 4))
        measurement_combo = ttk.Combobox(
            scope_measurement,
            textvariable=self.measurement_var,
            values=("Vpp", "Vrms", "Frequency", "Period", "Vmax", "Vmin"),
            width=11,
            state="readonly",
        )
        measurement_combo.pack(side="left", padx=(0, 8))
        ttk.Label(scope_measurement, text="Kanal").pack(side="left", padx=(0, 4))
        channel_spinbox = ttk.Spinbox(scope_measurement, from_=1, to=4, textvariable=self.channel_var, width=4)
        channel_spinbox.pack(side="left", padx=(0, 8))

        waveform_channels = ttk.Frame(scope)
        waveform_channels.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        waveform_button = ttk.Button(waveform_channels, text="Waveform", command=self.capture_waveform)
        waveform_button.pack(side="left", padx=(0, 8))
        ttk.Label(waveform_channels, text="Waveform-Kanäle").pack(side="left", padx=(0, 8))
        waveform_checkbuttons: list[tk.Widget] = []
        for channel, variable in self.waveform_channel_vars.items():
            checkbutton = ttk.Checkbutton(waveform_channels, text=f"CH{channel}", variable=variable)
            checkbutton.pack(side="left", padx=(0, 8))
            waveform_checkbuttons.append(checkbutton)
        all_button = ttk.Button(waveform_channels, text="Alle", command=self.select_all_waveform_channels)
        all_button.pack(side="left", padx=(8, 4))
        none_button = ttk.Button(waveform_channels, text="Keine", command=self.clear_waveform_channels)
        none_button.pack(side="left", padx=(0, 8))

        waveform_options = ttk.Frame(scope)
        waveform_options.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(waveform_options, text="Punktmodus").pack(side="left", padx=(0, 8))
        point_mode_combo = ttk.Combobox(
            waveform_options,
            textvariable=self.point_mode_var,
            values=("RAW", "NORMAL", "MAXIMUM"),
            width=10,
            state="readonly",
        )
        point_mode_combo.pack(side="left", padx=(0, 8))

        dmm = ttk.LabelFrame(measurement_area, text="Multimeter")
        dmm.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        dmm_value_button = ttk.Button(dmm, text="DMM Messwert", command=self.read_value)
        dmm_value_button.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Label(dmm, text="Für Geräte mit :READ? Unterstützung").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))

        timed = ttk.LabelFrame(measurement_area, text="Getimtes Messen")
        timed.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        timed_controls = ttk.Frame(timed)
        timed_controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        timed_dmm_button = ttk.Button(timed_controls, text="DMM Start", command=self.start_timed_dmm)
        timed_dmm_button.pack(side="left", padx=(0, 8))
        timed_scope_button = ttk.Button(timed_controls, text="Scope Start", command=self.start_timed_scope)
        timed_scope_button.pack(side="left", padx=(0, 8))
        timed_stop_button = ttk.Button(timed_controls, text="Stop", command=self.stop_timed_measurement)
        timed_stop_button.pack(side="left", padx=(0, 12))
        ttk.Label(timed_controls, text="Intervall [s]").pack(side="left", padx=(0, 4))
        timed_interval_entry = ttk.Entry(timed_controls, textvariable=self.timed_interval_var, width=8)
        timed_interval_entry.pack(side="left", padx=(0, 8))
        ttk.Label(timed_controls, text="Anzahl").pack(side="left", padx=(0, 4))
        timed_count_entry = ttk.Entry(timed_controls, textvariable=self.timed_count_var, width=8)
        timed_count_entry.pack(side="left", padx=(0, 8))

        vna = ttk.LabelFrame(measurement_area, text="Netzwerkanalysator")
        vna.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        sparameter_controls = ttk.Frame(vna)
        sparameter_controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        sparameter_button = ttk.Button(sparameter_controls, text="S-Parameter exportieren", command=self.capture_sparameters)
        sparameter_button.pack(side="left", padx=(0, 8))
        ttk.Label(sparameter_controls, text="Format").pack(side="left", padx=(0, 4))
        sparameter_format_combo = ttk.Combobox(
            sparameter_controls,
            textvariable=self.sparameter_format_var,
            values=("AUTO", "DB", "MA", "RI"),
            width=8,
            state="readonly",
        )
        sparameter_format_combo.pack(side="left", padx=(0, 12))
        ttk.Label(sparameter_controls, text="Ports").pack(side="left", padx=(0, 8))
        sparameter_checkbuttons: list[tk.Widget] = []
        for port, variable in self.sparameter_port_vars.items():
            checkbutton = ttk.Checkbutton(sparameter_controls, text=f"S{port}", variable=variable)
            checkbutton.pack(side="left", padx=(0, 8))
            sparameter_checkbuttons.append(checkbutton)

        common = ttk.LabelFrame(self, text="Allgemein")
        common.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        screenshot_button = ttk.Button(common, text="Screenshot", command=self.capture_screenshot)
        screenshot_button.pack(side="left", padx=8, pady=8)

        self._scope_widgets = [scope_value_button, measurement_combo, channel_spinbox, waveform_button, *waveform_checkbuttons, all_button, none_button, point_mode_combo]
        self._dmm_widgets = [dmm_value_button]
        self._vna_widgets = [sparameter_button, sparameter_format_combo, *sparameter_checkbuttons]
        self._screenshot_widgets = [screenshot_button]
        self._timed_widgets = [timed_dmm_button, timed_scope_button, timed_interval_entry, timed_count_entry]
        self._timed_dmm_widgets = [timed_dmm_button]
        self._timed_scope_widgets = [timed_scope_button]
        self._timed_stop_widgets = [timed_stop_button]
        self._refresh_resource_combo()
        self._apply_saved_profile_for_address()

        log_frame = ttk.LabelFrame(self, text="Protokoll")
        log_frame.grid(row=4, column=0, sticky="nsew", padx=12, pady=6)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.log.configure(yscrollcommand=scrollbar.set)

        status = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 12))

    def search_devices(self) -> None:
        self._run_worker("Gerätesuche läuft...", self._search_devices)

    def select_device(self, event: tk.Event | None = None) -> None:
        selected = self.resource_var.get().strip()
        if not selected:
            return
        self.address_var.set(self.resource_display_map.get(selected, selected))
        self._apply_saved_profile_for_address()
        if self._saved_device_for_address(self.address_var.get().strip()):
            self.status_var.set("Bekanntes Gerät ausgewählt.")
        else:
            self.status_var.set("Gerät ausgewählt. Für Typ-Erkennung bitte IDN testen.")

    def apply_saved_profile(self, event: tk.Event | None = None) -> None:
        self._apply_saved_profile_for_address()

    def test_idn(self) -> None:
        self._run_worker("IDN-Abfrage läuft...", self._test_idn)

    def read_value(self) -> None:
        self._run_worker("DMM-Messwert wird gelesen...", self._read_value)

    def read_scope_measurement(self) -> None:
        self._run_worker("Scope-Messwert wird gelesen...", self._read_scope_measurement)

    def capture_screenshot(self) -> None:
        self._run_worker("Screenshot wird erfasst...", self._capture_screenshot)

    def capture_waveform(self) -> None:
        self._run_worker("Waveform wird erfasst...", self._capture_waveform)

    def capture_sparameters(self) -> None:
        self._run_worker("S-Parameter werden exportiert...", self._capture_sparameters)

    def start_timed_dmm(self) -> None:
        self._start_timed_measurement("dmm")

    def start_timed_scope(self) -> None:
        self._start_timed_measurement("scope")

    def stop_timed_measurement(self) -> None:
        self.timed_stop_event.set()
        self.status_var.set("Getimtes Messen wird gestoppt...")

    def _start_timed_measurement(self, mode: str) -> None:
        if self.timed_running:
            messagebox.showwarning("Getimtes Messen", "Es läuft bereits eine Messreihe.")
            return
        try:
            self._timed_interval()
            self._timed_count()
        except ValueError as exc:
            messagebox.showerror("Getimtes Messen", str(exc))
            return
        self.timed_stop_event.clear()
        self.timed_running = True
        self._set_timed_running(True)
        label = "DMM" if mode == "dmm" else "Scope"
        self.status_var.set(f"Getimtes {label}-Messen läuft...")
        self._append_log(f"Getimtes {label}-Messen läuft...")
        self.logger.info("Getimtes %s-Messen läuft...", label)
        thread = threading.Thread(target=self._worker_target, args=(lambda: self._timed_measurement(mode),), daemon=True)
        thread.start()

    def choose_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Excel-Datei auswählen",
            defaultextension=".xlsx",
            filetypes=[("Excel-Dateien", "*.xlsx"), ("Alle Dateien", "*.*")],
            initialfile=Path(self.output_var.get()).name,
        )
        if selected:
            self.output_var.set(selected)

    def open_excel(self) -> None:
        output_path = self._output_path()
        if not output_path.exists():
            messagebox.showwarning("Excel öffnen", f"Datei existiert noch nicht: {output_path}")
            return
        os.startfile(output_path)

    def open_output_folder(self) -> None:
        output_path = self._output_path()
        folder = output_path.parent if output_path.parent != Path("") else Path.cwd()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def select_all_waveform_channels(self) -> None:
        for variable in self.waveform_channel_vars.values():
            variable.set(True)

    def clear_waveform_channels(self) -> None:
        for variable in self.waveform_channel_vars.values():
            variable.set(False)

    def _search_devices(self) -> str:
        resources = list_resources()
        if resources:
            self._messages.put(("resources", "\n".join(resources)))
            return "Gefundene Geräte:\n" + "\n".join(resources)
        return "Keine VISA-Geräte gefunden. Bekannte Adresse kann manuell eingetragen werden."

    def _test_idn(self) -> str:
        address = self.address_var.get().strip()
        with self._open_instrument() as instrument:
            idn = instrument.info().idn
        profile = detect_profile(idn)
        self._messages.put(("profile", (profile, address, idn)))
        self.logger.info("IDN address=%s idn=%s device_type=%s profile=%s %s", address, idn, profile.device_type, profile.manufacturer, profile.model_family)
        return f"{idn}\nGerätetyp: {profile.device_type}\nProfil: {profile.manufacturer} {profile.model_family}"

    def _read_value(self) -> str:
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = read_value(instrument)
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("DMM value exported workbook=%s value=%s", export.workbook_path, result.content)
        return f"Messwert gespeichert: {export.workbook_path}\n{result.content}"

    def _read_scope_measurement(self) -> str:
        measurement = self.measurement_var.get()
        channel = self.channel_var.get()
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = read_scope_measurement(instrument, measurement, channel, info.idn)
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Scope value exported workbook=%s measurement=%s channel=%s value=%s", export.workbook_path, measurement, channel, result.content)
        return f"Scope-Messwert gespeichert: {export.workbook_path}\n{measurement} CH{channel}: {result.content}"

    def _capture_screenshot(self) -> str:
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = capture_screenshot(instrument, info.idn)
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Screenshot exported workbook=%s artifact=%s sheet=%s", export.workbook_path, export.artifact_path, export.sheet_name)
        if export.artifact_path is not None:
            sheet_text = f"\nTabellenblatt: {export.sheet_name}" if export.sheet_name else ""
            return f"Screenshot gespeichert: {export.workbook_path}{sheet_text}\nPNG-Datei: {export.artifact_path}"
        return f"Screenshot gespeichert: {export.workbook_path}"

    def _capture_waveform(self) -> str:
        channels = [channel for channel, variable in self.waveform_channel_vars.items() if variable.get()]
        if not channels:
            raise ValueError("Bitte mindestens einen Waveform-Kanal auswählen.")
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = capture_waveform(instrument, info.idn, channels, self.point_mode_var.get())
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Waveform exported workbook=%s sheet=%s channels=%s point_mode=%s", export.workbook_path, export.sheet_name, channels, self.point_mode_var.get())
        channel_text = ", ".join(f"CH{channel}" for channel in channels)
        sheet_text = f"\nTabellenblatt: {export.sheet_name}" if export.sheet_name else ""
        return f"Waveform gespeichert: {export.workbook_path}{sheet_text}\nKanäle: {channel_text}\nPunktmodus: {self.point_mode_var.get()}"

    def _capture_sparameters(self) -> str:
        ports = [port for port, variable in self.sparameter_port_vars.items() if variable.get()]
        if not ports:
            raise ValueError("Bitte mindestens einen S-Parameter-Port auswählen.")
        config = SParameterConfig(
            format=self.sparameter_format_var.get(),
            s1=1 in ports,
            s2=2 in ports,
            s3=3 in ports,
            s4=4 in ports,
        )
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = capture_sparameters(instrument, info.idn, config)
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("S-parameters exported workbook=%s artifact=%s ports=%s format=%s", export.workbook_path, export.artifact_path, ports, config.format)
        artifact_text = f"\nDatei: {export.artifact_path}" if export.artifact_path else ""
        port_text = ", ".join(f"S{port}" for port in ports)
        return f"S-Parameter gespeichert: {export.workbook_path}{artifact_text}\nPorts: {port_text}\nFormat: {config.format}"

    def _timed_measurement(self, mode: str) -> str:
        interval_s = self._timed_interval()
        count = self._timed_count()
        address = self.address_var.get().strip()
        measurement = self.measurement_var.get()
        channel = self.channel_var.get()
        rows = [["Index", "Timestamp", "ElapsedSeconds", "DeltaSeconds", "ScheduleOffsetSeconds", "Mode", "Measurement", "Channel", "Value", "Status"]]
        started_at = datetime.now()
        started = monotonic()
        last_elapsed_s: float | None = None
        ok_count = 0
        error_count = 0

        try:
            with self._open_instrument() as instrument:
                info = instrument.info()
                for index in range(1, count + 1):
                    if self.timed_stop_event.is_set():
                        break

                    scheduled_elapsed_s = (index - 1) * interval_s
                    wait_s = started + scheduled_elapsed_s - monotonic()
                    if wait_s > 0 and self.timed_stop_event.wait(wait_s):
                        break

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    elapsed_s = monotonic() - started
                    delta_s = 0.0 if last_elapsed_s is None else elapsed_s - last_elapsed_s
                    schedule_offset_s = elapsed_s - scheduled_elapsed_s
                    last_elapsed_s = elapsed_s
                    try:
                        if mode == "dmm":
                            result = read_value(instrument)
                            measurement_label = "DMM :READ?"
                            channel_value = ""
                        else:
                            result = read_scope_measurement(instrument, measurement, channel, info.idn)
                            measurement_label = measurement
                            channel_value = f"CH{channel}"
                        value = result.content
                        status = "OK"
                        ok_count += 1
                    except Exception as exc:
                        value = ""
                        status = f"ERROR: {exc}"
                        error_count += 1

                    rows.append([index, timestamp, f"{elapsed_s:.3f}", f"{delta_s:.3f}", f"{schedule_offset_s:.3f}", mode.upper(), measurement_label, channel_value, value, status])
                    self._messages.put(("progress", f"Messung {index}/{count}: {value if value else status}"))
        finally:
            self.timed_running = False
            self._messages.put(("timed_done", ""))

        if len(rows) == 1:
            raise ValueError("Messreihe wurde vor dem ersten Messwert gestoppt.")

        actual_count = len(rows) - 1
        finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows.extend(
            [
                [],
                ["Summary", ""],
                ["StartedAt", started_at.strftime("%Y-%m-%d %H:%M:%S")],
                ["FinishedAt", finished],
                ["RequestedIntervalSeconds", f"{interval_s:.3f}"],
                ["RequestedCount", count],
                ["ActualCount", actual_count],
                ["OkCount", ok_count],
                ["ErrorCount", error_count],
                ["StoppedByUser", "Yes" if self.timed_stop_event.is_set() else "No"],
            ]
        )

        result = AcquisitionResult(kind=f"timed {mode}", file_type="csv", content=_csv_rows(rows))
        export = append_result(self._output_path(), address, info.idn, result)
        stopped_text = " gestoppt" if self.timed_stop_event.is_set() else " abgeschlossen"
        self.logger.info("Timed measurement exported workbook=%s sheet=%s mode=%s count=%s ok=%s errors=%s interval=%s", export.workbook_path, export.sheet_name, mode, actual_count, ok_count, error_count, interval_s)
        return f"Getimtes {mode.upper()}-Messen{stopped_text}: {export.workbook_path}\nTabellenblatt: {export.sheet_name}\nMesspunkte: {actual_count}\nOK: {ok_count}, Fehler: {error_count}"

    def _timed_interval(self) -> float:
        try:
            interval_s = float(self.timed_interval_var.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Intervall muss eine Zahl in Sekunden sein.") from exc
        if interval_s <= 0:
            raise ValueError("Intervall muss größer als 0 sein.")
        return interval_s

    def _timed_count(self) -> int:
        try:
            count = int(self.timed_count_var.get())
        except ValueError as exc:
            raise ValueError("Anzahl muss eine ganze Zahl sein.") from exc
        if count <= 0:
            raise ValueError("Anzahl muss größer als 0 sein.")
        return count

    def _open_instrument(self) -> VisaInstrument:
        address = self.address_var.get().strip()
        if not address:
            raise ValueError("Bitte eine VISA-Adresse eintragen.")
        return VisaInstrument(address=address, timeout_ms=10000)

    def _output_path(self) -> Path:
        output = self.output_var.get().strip()
        if not output:
            raise ValueError("Bitte eine Excel-Datei auswählen.")
        return Path(output)

    def _run_worker(self, status: str, action) -> None:
        self.status_var.set(status)
        self._append_log(status)
        self.logger.info(status)
        thread = threading.Thread(target=self._worker_target, args=(action,), daemon=True)
        thread.start()

    def _worker_target(self, action) -> None:
        try:
            message = action()
        except Exception as exc:
            formatted_error = self._format_error(exc)
            self.logger.exception(formatted_error)
            self._messages.put(("error", formatted_error))
        else:
            self.logger.info(message)
            self._messages.put(("success", message))

    def _process_messages(self) -> None:
        while True:
            try:
                kind, message = self._messages.get_nowait()
            except queue.Empty:
                break
            if kind == "resources":
                if isinstance(message, str):
                    self._apply_resources(message.splitlines())
            elif kind == "profile":
                self._apply_profile_message(message)
            elif kind == "progress":
                if isinstance(message, str):
                    self.status_var.set(message)
                    self._append_log(message)
            elif kind == "timed_done":
                self._set_timed_running(False)
            elif kind == "error":
                self.status_var.set("Fehler")
                error_message = str(message)
                self._append_log(f"Fehler: {error_message}")
                messagebox.showerror("Fehler", error_message)
            else:
                self.status_var.set("Bereit")
                self._append_log(str(message))
        self.after(100, self._process_messages)

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _apply_resources(self, resources: list[str]) -> None:
        self.last_found_resources = list(dict.fromkeys(resources))
        self._refresh_resource_combo(resources)
        if not resources:
            self.status_var.set("Keine VISA-Geräte gefunden. Bekannte Geräte bleiben in der Liste.")
            return
        current_address = self.address_var.get().strip()
        selected_resource = current_address if current_address in resources else resources[0]
        self.resource_var.set(self._resource_display_label(selected_resource))
        self.address_var.set(selected_resource)
        self._apply_saved_profile_for_address()
        self.status_var.set("Gerätesuche abgeschlossen. Für neue Geräte bitte IDN testen.")

    def _refresh_resource_combo(self, resources: list[str] | None = None) -> None:
        resources = self.last_found_resources if resources is None else resources
        values: list[str] = []
        self.resource_display_map = {}
        for address in self._known_device_addresses():
            display_address = self._display_address_for_known_device(address)
            label = self._resource_display_label(display_address)
            values.append(label)
            self.resource_display_map[label] = display_address
        for address in dict.fromkeys(resources or []):
            label = self._resource_display_label(address)
            if label not in self.resource_display_map:
                values.append(label)
            self.resource_display_map[label] = address
        self.resource_combo.configure(values=values)

        current_address = self.address_var.get().strip()
        if current_address:
            current_label = self._resource_display_label(current_address)
            if current_label in self.resource_display_map:
                self.resource_var.set(current_label)
        elif values:
            self.resource_var.set(values[0])
            self.address_var.set(self.resource_display_map[values[0]])

    def _known_device_addresses(self) -> list[str]:
        return sorted(self.saved_devices, key=lambda address: self._resource_display_label(address).lower())

    def _resource_display_label(self, address: str) -> str:
        saved = self._saved_device_for_address(address)
        if isinstance(saved, dict):
            device_type = str(saved.get("device_type", "")).strip()
            manufacturer = str(saved.get("manufacturer", "")).strip()
            model_family = str(saved.get("model_family", "")).strip()
            description = " ".join(part for part in (device_type, manufacturer, model_family) if part and part != "Unbekannt")
            if description:
                return f"{description} - {address}"
        return address

    def _display_address_for_known_device(self, address: str) -> str:
        saved = self.saved_devices.get(address)
        if isinstance(saved, dict):
            return str(saved.get("address", address)).strip() or address
        return address

    def _saved_device_for_address(self, address: str) -> dict | None:
        saved = self.saved_devices.get(address)
        if isinstance(saved, dict):
            return saved
        canonical_address = self._canonical_address(address)
        saved = self.saved_devices.get(canonical_address)
        if isinstance(saved, dict):
            return saved
        for known_address, known_device in self.saved_devices.items():
            if self._canonical_address(known_address) == canonical_address and isinstance(known_device, dict):
                return known_device
        return None

    def _canonical_address(self, address: str) -> str:
        parts = address.split("::")
        if len(parts) >= 6 and parts[-1] == "INSTR" and parts[-2].isdigit():
            return "::".join([*parts[:-2], parts[-1]])
        return address

    def _apply_device_type(self, device_type: str) -> None:
        if device_type == "Nicht erkannt":
            self._apply_profile(UNKNOWN_PROFILE)
        else:
            self._apply_profile(DeviceProfile("Unbekannt", "Unbekannt", device_type))

    def _apply_profile(self, profile: DeviceProfile) -> None:
        self.current_profile = profile
        self.device_type_var.set(profile.device_type)
        self.profile_var.set(f"Profil: {profile.manufacturer} {profile.model_family}")
        scope_enabled = profile.supports_scope_measurements or profile.supports_waveform
        scope_measurement_enabled = profile.supports_scope_measurements
        dmm_enabled = profile.supports_dmm_read
        timed_enabled = scope_measurement_enabled or dmm_enabled
        vna_enabled = profile.supports_sparameters
        screenshot_enabled = profile.supports_screenshot
        self._set_widgets_enabled(self._scope_widgets, scope_enabled)
        self._set_widgets_enabled(self._dmm_widgets, dmm_enabled)
        self._set_widgets_enabled(self._timed_widgets, timed_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_dmm_widgets, dmm_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_scope_widgets, scope_measurement_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_stop_widgets, self.timed_running)
        self._set_widgets_enabled(self._vna_widgets, vna_enabled)
        self._set_widgets_enabled(self._screenshot_widgets, screenshot_enabled)

    def _apply_profile_message(self, message: object) -> None:
        if isinstance(message, tuple) and len(message) == 3:
            profile, address, idn = message
            if isinstance(profile, DeviceProfile) and isinstance(address, str) and isinstance(idn, str):
                self._remember_device(address, idn, profile)
                self._apply_profile(profile)
                return
        if isinstance(message, DeviceProfile):
            self._apply_profile(message)

    def _apply_saved_profile_for_address(self) -> None:
        address = self.address_var.get().strip()
        saved = self._saved_device_for_address(address)
        if isinstance(saved, dict):
            self._apply_profile(self._profile_from_settings(saved))
        else:
            self._apply_profile(UNKNOWN_PROFILE)

    def _remember_device(self, address: str, idn: str, profile: DeviceProfile) -> None:
        if not address:
            return
        canonical_address = self._canonical_address(address)
        for known_address in list(self.saved_devices):
            if known_address != canonical_address and self._canonical_address(known_address) == canonical_address:
                del self.saved_devices[known_address]
        self.saved_devices[canonical_address] = {
            "address": address,
            "idn": idn,
            "manufacturer": profile.manufacturer,
            "model_family": profile.model_family,
            "device_type": profile.device_type,
            "key": profile.key,
            "supports_scope_measurements": profile.supports_scope_measurements,
            "supports_waveform": profile.supports_waveform,
            "supports_dmm_read": profile.supports_dmm_read,
            "supports_screenshot": profile.supports_screenshot,
            "supports_sparameters": profile.supports_sparameters,
        }
        self._refresh_resource_combo(self.last_found_resources)
        self._save_settings()

    def _profile_from_settings(self, saved: dict) -> DeviceProfile:
        return DeviceProfile(
            manufacturer=str(saved.get("manufacturer", "Unbekannt")),
            model_family=str(saved.get("model_family", "Unbekannt")),
            device_type=str(saved.get("device_type", "Unbekannt")),
            key=str(saved.get("key", "unknown")),
            supports_scope_measurements=bool(saved.get("supports_scope_measurements", False)),
            supports_waveform=bool(saved.get("supports_waveform", False)),
            supports_dmm_read=bool(saved.get("supports_dmm_read", False)),
            supports_screenshot=bool(saved.get("supports_screenshot", False)),
            supports_sparameters=bool(saved.get("supports_sparameters", False)),
        )

    def _set_timed_running(self, running: bool) -> None:
        self.timed_running = running
        scope_enabled = self.current_profile.supports_scope_measurements
        dmm_enabled = self.current_profile.supports_dmm_read
        self._set_widgets_enabled(self._timed_widgets, (scope_enabled or dmm_enabled) and not running)
        self._set_widgets_enabled(self._timed_dmm_widgets, dmm_enabled and not running)
        self._set_widgets_enabled(self._timed_scope_widgets, scope_enabled and not running)
        self._set_widgets_enabled(self._timed_stop_widgets, running)

    def _set_widgets_enabled(self, widgets: list[tk.Widget], enabled: bool) -> None:
        for widget in widgets:
            state = "readonly" if enabled and widget.winfo_class() == "TCombobox" else "normal" if enabled else "disabled"
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass

    def close(self) -> None:
        self._save_settings()
        self.destroy()

    def _load_settings(self) -> dict:
        if not SETTINGS_PATH.exists():
            return {}
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _load_saved_devices(self) -> dict[str, dict]:
        devices = self.settings.get("devices", {})
        if isinstance(devices, dict):
            return {str(address): device for address, device in devices.items() if isinstance(device, dict)}
        return {}

    def _save_settings(self) -> None:
        settings = {
            "window_geometry": self.geometry(),
            "address": self.address_var.get().strip(),
            "output": self.output_var.get().strip(),
            "measurement": self.measurement_var.get(),
            "channel": self.channel_var.get(),
            "timed_interval": self.timed_interval_var.get(),
            "timed_count": self.timed_count_var.get(),
            "point_mode": self.point_mode_var.get(),
            "waveform_channels": [channel for channel, variable in self.waveform_channel_vars.items() if variable.get()],
            "sparameter_format": self.sparameter_format_var.get(),
            "sparameter_ports": [port for port, variable in self.sparameter_port_vars.items() if variable.get()],
            "devices": self.saved_devices,
        }
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def _format_error(self, exc: Exception) -> str:
        text = str(exc)
        class_name = exc.__class__.__name__
        if "VI_ERROR_TMO" in text:
            return "Timeout: Das Gerät hat nicht rechtzeitig geantwortet. Prüfe Gerätetyp, Kanal, Verbindung und ob der Befehl vom Gerät unterstützt wird."
        if "VI_ERROR_RSRC_NFOUND" in text:
            return "VISA-Gerät nicht gefunden. Bitte Geräte suchen, Adresse prüfen oder die VISA-Verbindung neu herstellen."
        if isinstance(exc, PermissionError):
            return "Datei kann nicht geschrieben werden. Bitte Excel-Datei schließen und erneut versuchen."
        if "Unsupported" in text:
            return f"Diese Funktion wird für das erkannte Gerät noch nicht unterstützt. Details: {text}"
        return f"{class_name}: {text}"


def main() -> int:
    app = InstrumentVisaApp()
    app.mainloop()
    return 0


def _csv_rows(rows: list[list[object]]) -> str:
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
