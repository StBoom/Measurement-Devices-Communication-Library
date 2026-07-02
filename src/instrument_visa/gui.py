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

from .acquisition import (
    AcquisitionResult,
    capture_screenshot,
    capture_sparameters,
    capture_waveform,
    read_power_supply_settings,
    read_scope_measurement,
    read_signal_generator_settings,
    read_value,
    set_power_supply,
    set_power_supply_master_output,
    set_power_supply_output,
    set_signal_generator,
    set_signal_generator_rf_output,
)
from .config import SParameterConfig
from .excel_export import append_result
from .logging_utils import setup_logging
from .profiles import UNKNOWN_PROFILE, DeviceProfile, detect_profile, hmp_channel_count
from .sequence import (
    FrequencySweepConfig,
    TimedSwitchConfig,
    VoltageSweepConfig,
    frequency_points,
    parse_ampere,
    parse_dbm,
    parse_voltage,
    run_frequency_sweep,
    run_timed_switch,
    run_voltage_sweep,
    voltage_points,
)
from .visa_client import VisaInstrument, list_resources


DEFAULT_ADDRESS = "USB0::0x0957::0x1796::MY58104189::0::INSTR"
SETTINGS_PATH = Path("gui_settings.json")


class InstrumentVisaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Measurement Devices Communication Library")

        self.settings = self._load_settings()
        self.geometry(self.settings.get("window_geometry", "1280x760"))
        self.minsize(900, 680)
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
        self.generator_frequency_var = tk.StringVar(value=self.settings.get("generator_frequency", "100 MHz"))
        self.generator_power_var = tk.StringVar(value=self.settings.get("generator_power", "-30 dBm"))
        self.generator_rf_var = tk.StringVar(value=self.settings.get("generator_rf", "OFF"))
        self.generator_max_power_var = tk.StringVar(value=str(self.settings.get("generator_max_power", "0")))
        self.generator_rf_off_before_change_var = tk.BooleanVar(value=bool(self.settings.get("generator_rf_off_before_change", True)))
        self.power_supply_channel_var = tk.IntVar(value=int(self.settings.get("power_supply_channel", 1)))
        self.power_supply_voltage_var = tk.StringVar(value=self.settings.get("power_supply_voltage", "5 V"))
        self.power_supply_current_var = tk.StringVar(value=self.settings.get("power_supply_current", "0.5 A"))
        self.power_supply_output_var = tk.StringVar(value=self.settings.get("power_supply_output", "OFF"))
        self.power_supply_max_voltage_var = tk.StringVar(value=str(self.settings.get("power_supply_max_voltage", "32")))
        self.power_supply_max_current_var = tk.StringVar(value=str(self.settings.get("power_supply_max_current", "10")))
        self.sequence_generator_address_var = tk.StringVar(value=self.settings.get("sequence_generator_address", self.address_var.get()))
        self.sequence_measurement_address_var = tk.StringVar(value=self.settings.get("sequence_measurement_address", self.address_var.get()))
        self.sequence_source_type_var = tk.StringVar(value=self.settings.get("sequence_source_type", "Signalgenerator"))
        self.sequence_start_frequency_var = tk.StringVar(value=self.settings.get("sequence_start_frequency", "100 MHz"))
        self.sequence_stop_frequency_var = tk.StringVar(value=self.settings.get("sequence_stop_frequency", "110 MHz"))
        self.sequence_step_frequency_var = tk.StringVar(value=self.settings.get("sequence_step_frequency", "1 MHz"))
        self.sequence_power_var = tk.StringVar(value=self.settings.get("sequence_power", "-30 dBm"))
        self.sequence_supply_channel_var = tk.IntVar(value=int(self.settings.get("sequence_supply_channel", 1)))
        self.sequence_start_voltage_var = tk.StringVar(value=self.settings.get("sequence_start_voltage", "0 V"))
        self.sequence_stop_voltage_var = tk.StringVar(value=self.settings.get("sequence_stop_voltage", "5 V"))
        self.sequence_step_voltage_var = tk.StringVar(value=self.settings.get("sequence_step_voltage", "1 V"))
        self.sequence_current_limit_var = tk.StringVar(value=self.settings.get("sequence_current_limit", "0.1 A"))
        self.sequence_settle_var = tk.StringVar(value=str(self.settings.get("sequence_settle", "0.5")))
        self.sequence_measurement_mode_var = tk.StringVar(value=self.settings.get("sequence_measurement_mode", "DMM"))
        self.sequence_rf_off_at_end_var = tk.BooleanVar(value=bool(self.settings.get("sequence_rf_off_at_end", True)))
        self.switch_source_type_var = tk.StringVar(value=self.settings.get("switch_source_type", "Signalgenerator"))
        self.switch_address_var = tk.StringVar(value=self.settings.get("switch_address", self.address_var.get()))
        self.switch_on_s_var = tk.StringVar(value=str(self.settings.get("switch_on_s", "1")))
        self.switch_off_s_var = tk.StringVar(value=str(self.settings.get("switch_off_s", "1")))
        self.switch_repetitions_var = tk.StringVar(value=str(self.settings.get("switch_repetitions", "3")))
        self.switch_setup_before_var = tk.BooleanVar(value=bool(self.settings.get("switch_setup_before", False)))
        self.switch_end_off_var = tk.BooleanVar(value=bool(self.settings.get("switch_end_off", True)))
        self.switch_power_mode_var = tk.StringVar(value=self.settings.get("switch_power_mode", "Master"))
        self.status_var = tk.StringVar(value="Bereit")
        self._scope_widgets: list[tk.Widget] = []
        self._dmm_widgets: list[tk.Widget] = []
        self._vna_widgets: list[tk.Widget] = []
        self._screenshot_widgets: list[tk.Widget] = []
        self._timed_widgets: list[tk.Widget] = []
        self._timed_dmm_widgets: list[tk.Widget] = []
        self._timed_scope_widgets: list[tk.Widget] = []
        self._timed_stop_widgets: list[tk.Widget] = []
        self._generator_widgets: list[tk.Widget] = []
        self._power_supply_widgets: list[tk.Widget] = []
        self._sequence_widgets: list[tk.Widget] = []
        self._sequence_stop_widgets: list[tk.Widget] = []
        self._switch_widgets: list[tk.Widget] = []
        self._switch_stop_widgets: list[tk.Widget] = []
        self._device_sections: dict[str, tk.Widget] = {}
        self._power_supply_channel_spinbox: ttk.Spinbox | None = None
        self.timed_stop_event = threading.Event()
        self.sequence_stop_event = threading.Event()
        self.switch_stop_event = threading.Event()
        self.timed_running = False
        self.sequence_running = False
        self.switch_running = False
        self.current_profile: DeviceProfile = UNKNOWN_PROFILE
        self._messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._log_visible = bool(self.settings.get("log_visible", True))
        self._main_pane: ttk.Frame | None = None
        self._controls_container: ttk.Frame | None = None
        self._log_pane: ttk.Frame | None = None
        self._log_frame: ttk.LabelFrame | None = None
        self._collapsed_log_button: ttk.Button | None = None
        self._last_controls_width: int | None = None
        self._log_toggle_var = tk.StringVar()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self._process_messages)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)

        main_pane = ttk.Frame(self)
        main_pane.grid(row=0, column=0, sticky="nsew")
        main_pane.columnconfigure(0, weight=1)
        main_pane.columnconfigure(1, weight=0)
        main_pane.rowconfigure(0, weight=1)
        self._main_pane = main_pane
        collapsed_log_button = ttk.Button(self, text="‹", width=3, command=self.toggle_log)
        self._collapsed_log_button = collapsed_log_button

        controls_container = ttk.Frame(main_pane)
        self._controls_container = controls_container
        controls_container.grid(row=0, column=0, sticky="nsew")
        controls_container.columnconfigure(0, weight=1)
        controls_container.rowconfigure(0, weight=1)
        controls_canvas = tk.Canvas(controls_container, highlightthickness=0)
        controls_scrollbar = ttk.Scrollbar(controls_container, orient="vertical", command=controls_canvas.yview)
        controls_canvas.grid(row=0, column=0, sticky="nsew")
        controls_scrollbar.grid(row=0, column=1, sticky="ns")
        controls_frame = ttk.Frame(controls_canvas)
        controls_frame.columnconfigure(0, weight=1)
        controls_window = controls_canvas.create_window((0, 0), window=controls_frame, anchor="nw")
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_frame.bind("<Configure>", lambda event: controls_canvas.configure(scrollregion=controls_canvas.bbox("all")))
        controls_canvas.bind("<Configure>", lambda event: controls_canvas.itemconfigure(controls_window, width=event.width))
        controls_container.bind("<Enter>", lambda event: controls_canvas.bind_all("<MouseWheel>", lambda wheel_event: self._scroll_controls_if_needed(controls_canvas, wheel_event)))
        controls_container.bind("<Leave>", lambda event: controls_canvas.unbind_all("<MouseWheel>"))
        log_pane = ttk.Frame(main_pane)
        self._log_pane = log_pane
        log_pane.columnconfigure(1, weight=1)
        log_pane.rowconfigure(0, weight=1)
        log_toggle_button = ttk.Button(log_pane, textvariable=self._log_toggle_var, width=3, command=self.toggle_log)
        log_toggle_button.grid(row=0, column=0, sticky="ns", padx=(4, 2), pady=4)
        log_frame = ttk.LabelFrame(log_pane, text="Protokoll")
        self._log_frame = log_frame
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        connection = ttk.LabelFrame(controls_frame, text="Verbindung")
        connection.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        connection.columnconfigure(1, weight=1)

        ttk.Label(connection, text="Gefundene Geräte").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.resource_combo = ttk.Combobox(connection, textvariable=self.resource_var, state="readonly")
        self.resource_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        self.resource_combo.bind("<<ComboboxSelected>>", self.select_device)
        search_button = ttk.Button(connection, text="Geräte suchen", command=self.search_devices)
        search_button.grid(row=0, column=2, padx=8, pady=8)
        idn_button = ttk.Button(connection, text="IDN testen", command=self.test_idn)
        idn_button.grid(row=0, column=3, padx=8, pady=8)
        ttk.Label(connection, text="VISA-Adresse").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        address_entry = ttk.Entry(connection, textvariable=self.address_var)
        address_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))
        address_entry.bind("<FocusOut>", self.apply_saved_profile)
        address_entry.bind("<Return>", self.apply_saved_profile)
        ttk.Label(connection, text="Gerätetyp").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Label(connection, textvariable=self.device_type_var).grid(row=2, column=1, sticky="w", padx=8, pady=(0, 8))
        ttk.Label(connection, textvariable=self.profile_var).grid(row=2, column=2, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        export = ttk.LabelFrame(controls_frame, text="Export")
        export.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        export.columnconfigure(1, weight=1)

        ttk.Label(export, text="Excel-Datei").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(export, textvariable=self.output_var).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(export, text="Auswählen", command=self.choose_output).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(export, text="Excel öffnen", command=self.open_excel).grid(row=0, column=3, padx=8, pady=8)
        ttk.Button(export, text="Ordner öffnen", command=self.open_output_folder).grid(row=0, column=4, padx=8, pady=8)

        measurement_area = ttk.Frame(controls_frame)
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

        generator = ttk.LabelFrame(measurement_area, text="Signalgenerator")
        generator.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        generator.columnconfigure(0, weight=1)

        generator_controls = ttk.Frame(generator)
        generator_controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        generator_read_button = ttk.Button(generator_controls, text="Generator lesen", command=self.read_signal_generator)
        generator_read_button.pack(side="left", padx=(0, 8))
        generator_set_button = ttk.Button(generator_controls, text="Generator setzen", command=self.set_signal_generator)
        generator_set_button.pack(side="left", padx=(0, 8))
        generator_rf_off_button = ttk.Button(generator_controls, text="RF Aus", command=self.signal_generator_rf_off)
        generator_rf_off_button.pack(side="left", padx=(0, 12))

        generator_settings = ttk.Frame(generator)
        generator_settings.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        generator_settings.columnconfigure(1, weight=1)
        generator_settings.columnconfigure(3, weight=1)
        ttk.Label(generator_settings, text="Frequenz").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=(0, 6))
        generator_frequency_entry = ttk.Entry(generator_settings, textvariable=self.generator_frequency_var, width=14)
        generator_frequency_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(0, 6))
        ttk.Label(generator_settings, text="Pegel").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=(0, 6))
        generator_power_entry = ttk.Entry(generator_settings, textvariable=self.generator_power_var, width=12)
        generator_power_entry.grid(row=0, column=3, sticky="ew", padx=(0, 12), pady=(0, 6))
        ttk.Label(generator_settings, text="RF").grid(row=0, column=4, sticky="w", padx=(0, 4), pady=(0, 6))
        generator_rf_combo = ttk.Combobox(generator_settings, textvariable=self.generator_rf_var, values=("OFF", "ON"), width=5, state="readonly")
        generator_rf_combo.grid(row=0, column=5, sticky="w", padx=(0, 12), pady=(0, 6))
        ttk.Label(generator_settings, text="Max. Pegel [dBm]").grid(row=1, column=0, sticky="w", padx=(0, 4))
        generator_max_power_entry = ttk.Entry(generator_settings, textvariable=self.generator_max_power_var, width=7)
        generator_max_power_entry.grid(row=1, column=1, sticky="w", padx=(0, 12))
        generator_rf_off_check = ttk.Checkbutton(generator_settings, text="RF vor Änderung aus", variable=self.generator_rf_off_before_change_var)
        generator_rf_off_check.grid(row=1, column=2, columnspan=4, sticky="w")

        power_supply = ttk.LabelFrame(measurement_area, text="Netzgerät")
        power_supply.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        power_supply.columnconfigure(0, weight=1)
        power_supply_controls = ttk.Frame(power_supply)
        power_supply_controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        power_supply_read_button = ttk.Button(power_supply_controls, text="Netzgerät lesen", command=self.read_power_supply)
        power_supply_read_button.pack(side="left", padx=(0, 8))
        power_supply_set_button = ttk.Button(power_supply_controls, text="Netzgerät setzen", command=self.set_power_supply)
        power_supply_set_button.pack(side="left", padx=(0, 8))
        power_supply_output_off_button = ttk.Button(power_supply_controls, text="Kanal Aus", command=self.power_supply_output_off)
        power_supply_output_off_button.pack(side="left", padx=(0, 12))
        power_supply_all_off_button = ttk.Button(power_supply_controls, text="Alle Aus", command=self.power_supply_all_outputs_off)
        power_supply_all_off_button.pack(side="left", padx=(0, 12))

        power_supply_settings = ttk.Frame(power_supply)
        power_supply_settings.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        power_supply_settings.columnconfigure(3, weight=1)
        ttk.Label(power_supply_settings, text="Kanal").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=(0, 6))
        power_supply_channel_spinbox = ttk.Spinbox(power_supply_settings, from_=1, to=4, textvariable=self.power_supply_channel_var, width=4)
        power_supply_channel_spinbox.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=(0, 6))
        ttk.Label(power_supply_settings, text="Spannung").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=(0, 6))
        power_supply_voltage_entry = ttk.Entry(power_supply_settings, textvariable=self.power_supply_voltage_var, width=10)
        power_supply_voltage_entry.grid(row=0, column=3, sticky="ew", padx=(0, 12), pady=(0, 6))
        ttk.Label(power_supply_settings, text="Stromlimit").grid(row=0, column=4, sticky="w", padx=(0, 4), pady=(0, 6))
        power_supply_current_entry = ttk.Entry(power_supply_settings, textvariable=self.power_supply_current_var, width=10)
        power_supply_current_entry.grid(row=0, column=5, sticky="w", padx=(0, 12), pady=(0, 6))
        ttk.Label(power_supply_settings, text="Ausgang").grid(row=0, column=6, sticky="w", padx=(0, 4), pady=(0, 6))
        power_supply_output_combo = ttk.Combobox(power_supply_settings, textvariable=self.power_supply_output_var, values=("OFF", "ON"), width=5, state="readonly")
        power_supply_output_combo.grid(row=0, column=7, sticky="w", padx=(0, 8), pady=(0, 6))
        ttk.Label(power_supply_settings, text="Max. V").grid(row=1, column=0, sticky="w", padx=(0, 4))
        power_supply_max_voltage_entry = ttk.Entry(power_supply_settings, textvariable=self.power_supply_max_voltage_var, width=7)
        power_supply_max_voltage_entry.grid(row=1, column=1, sticky="w", padx=(0, 12))
        ttk.Label(power_supply_settings, text="Max. A").grid(row=1, column=2, sticky="w", padx=(0, 4))
        power_supply_max_current_entry = ttk.Entry(power_supply_settings, textvariable=self.power_supply_max_current_var, width=7)
        power_supply_max_current_entry.grid(row=1, column=3, sticky="w", padx=(0, 12))

        common = ttk.LabelFrame(controls_frame, text="Allgemein")
        common.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        screenshot_button = ttk.Button(common, text="Screenshot", command=self.capture_screenshot)
        screenshot_button.pack(side="left", padx=8, pady=8)

        sequence = ttk.LabelFrame(controls_frame, text="Automatischer Ablauf")
        sequence.grid(row=4, column=0, sticky="ew", padx=12, pady=6)
        sequence.columnconfigure(1, weight=1)
        sequence.columnconfigure(3, weight=1)

        ttk.Label(sequence, text="Quellgerät").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        sequence_source_type_combo = ttk.Combobox(sequence, textvariable=self.sequence_source_type_var, values=("Signalgenerator", "Netzgerät"), width=16, state="readonly")
        sequence_source_type_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=(8, 4))
        ttk.Label(sequence, text="Quell-Adresse").grid(row=0, column=2, sticky="w", padx=8, pady=(8, 4))
        sequence_generator_entry = ttk.Entry(sequence, textvariable=self.sequence_generator_address_var)
        sequence_generator_entry.grid(row=0, column=3, sticky="ew", padx=8, pady=(8, 4))
        sequence_generator_current_button = ttk.Button(sequence, text="aktuelle Adresse", command=self.use_current_address_as_sequence_generator)
        sequence_generator_current_button.grid(row=0, column=4, sticky="ew", padx=8, pady=(8, 4))

        ttk.Label(sequence, text="Messgerät-Adresse").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        sequence_measurement_entry = ttk.Entry(sequence, textvariable=self.sequence_measurement_address_var)
        sequence_measurement_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=4)
        sequence_measurement_current_button = ttk.Button(sequence, text="aktuelle Adresse", command=self.use_current_address_as_sequence_measurement)
        sequence_measurement_current_button.grid(row=1, column=4, sticky="ew", padx=8, pady=4)

        ttk.Label(sequence, text="Generator Start").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        sequence_start_entry = ttk.Entry(sequence, textvariable=self.sequence_start_frequency_var, width=12)
        sequence_start_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(sequence, text="Stop").grid(row=2, column=2, sticky="w", padx=8, pady=4)
        sequence_stop_entry = ttk.Entry(sequence, textvariable=self.sequence_stop_frequency_var, width=12)
        sequence_stop_entry.grid(row=2, column=3, sticky="ew", padx=8, pady=4)
        ttk.Label(sequence, text="Schritt").grid(row=2, column=4, sticky="w", padx=8, pady=4)
        sequence_step_entry = ttk.Entry(sequence, textvariable=self.sequence_step_frequency_var, width=12)
        sequence_step_entry.grid(row=2, column=5, sticky="ew", padx=8, pady=4)

        ttk.Label(sequence, text="Generator Pegel").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        sequence_power_entry = ttk.Entry(sequence, textvariable=self.sequence_power_var, width=12)
        sequence_power_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(sequence, text="Netzteil Kanal").grid(row=3, column=2, sticky="w", padx=8, pady=4)
        sequence_supply_channel_spinbox = ttk.Spinbox(sequence, from_=1, to=4, textvariable=self.sequence_supply_channel_var, width=4)
        sequence_supply_channel_spinbox.grid(row=3, column=3, sticky="ew", padx=8, pady=4)

        ttk.Label(sequence, text="Netzteil Start").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        sequence_voltage_start_entry = ttk.Entry(sequence, textvariable=self.sequence_start_voltage_var, width=12)
        sequence_voltage_start_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(sequence, text="Stop").grid(row=4, column=2, sticky="w", padx=8, pady=4)
        sequence_voltage_stop_entry = ttk.Entry(sequence, textvariable=self.sequence_stop_voltage_var, width=12)
        sequence_voltage_stop_entry.grid(row=4, column=3, sticky="ew", padx=8, pady=4)
        ttk.Label(sequence, text="Schritt").grid(row=4, column=4, sticky="w", padx=8, pady=4)
        sequence_voltage_step_entry = ttk.Entry(sequence, textvariable=self.sequence_step_voltage_var, width=12)
        sequence_voltage_step_entry.grid(row=4, column=5, sticky="ew", padx=8, pady=4)

        ttk.Label(sequence, text="Stromlimit").grid(row=5, column=0, sticky="w", padx=8, pady=4)
        sequence_current_limit_entry = ttk.Entry(sequence, textvariable=self.sequence_current_limit_var, width=12)
        sequence_current_limit_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(sequence, text="Wartezeit [s]").grid(row=5, column=2, sticky="w", padx=8, pady=4)
        sequence_settle_entry = ttk.Entry(sequence, textvariable=self.sequence_settle_var, width=8)
        sequence_settle_entry.grid(row=5, column=3, sticky="ew", padx=8, pady=4)
        ttk.Label(sequence, text="Messart").grid(row=5, column=4, sticky="w", padx=8, pady=4)
        sequence_mode_combo = ttk.Combobox(sequence, textvariable=self.sequence_measurement_mode_var, values=("DMM", "Scope"), width=8, state="readonly")
        sequence_mode_combo.grid(row=5, column=5, sticky="ew", padx=8, pady=4)

        sequence_rf_off_check = ttk.Checkbutton(sequence, text="RF am Ende aus", variable=self.sequence_rf_off_at_end_var)
        sequence_rf_off_check.grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 8))
        sequence_preview_button = ttk.Button(sequence, text="Vorschau", command=self.preview_sequence)
        sequence_preview_button.grid(row=6, column=3, sticky="ew", padx=8, pady=(4, 8))
        sequence_start_button = ttk.Button(sequence, text="Ablauf starten", command=self.start_sequence)
        sequence_start_button.grid(row=6, column=4, sticky="ew", padx=8, pady=(4, 8))
        sequence_stop_button = ttk.Button(sequence, text="Stop", command=self.stop_sequence)
        sequence_stop_button.grid(row=6, column=5, sticky="ew", padx=8, pady=(4, 8))

        timed_switch = ttk.LabelFrame(controls_frame, text="Getimtes Schalten")
        timed_switch.grid(row=5, column=0, sticky="ew", padx=12, pady=6)
        timed_switch.columnconfigure(1, weight=1)
        timed_switch.columnconfigure(3, weight=1)
        ttk.Label(timed_switch, text="Quellgerät").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        switch_source_combo = ttk.Combobox(timed_switch, textvariable=self.switch_source_type_var, values=("Signalgenerator", "Netzgerät"), width=16, state="readonly")
        switch_source_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=(8, 4))
        ttk.Label(timed_switch, text="Adresse").grid(row=0, column=2, sticky="w", padx=8, pady=(8, 4))
        switch_address_entry = ttk.Entry(timed_switch, textvariable=self.switch_address_var)
        switch_address_entry.grid(row=0, column=3, sticky="ew", padx=8, pady=(8, 4))
        switch_current_button = ttk.Button(timed_switch, text="aktuelle Adresse", command=self.use_current_address_as_switch_source)
        switch_current_button.grid(row=0, column=4, sticky="ew", padx=8, pady=(8, 4))

        ttk.Label(timed_switch, text="ON-Dauer [s]").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        switch_on_entry = ttk.Entry(timed_switch, textvariable=self.switch_on_s_var, width=8)
        switch_on_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(timed_switch, text="OFF-Dauer [s]").grid(row=1, column=2, sticky="w", padx=8, pady=4)
        switch_off_entry = ttk.Entry(timed_switch, textvariable=self.switch_off_s_var, width=8)
        switch_off_entry.grid(row=1, column=3, sticky="ew", padx=8, pady=4)
        ttk.Label(timed_switch, text="Wiederholungen").grid(row=1, column=4, sticky="w", padx=8, pady=4)
        switch_repetitions_entry = ttk.Entry(timed_switch, textvariable=self.switch_repetitions_var, width=8)
        switch_repetitions_entry.grid(row=1, column=5, sticky="ew", padx=8, pady=4)

        switch_setup_check = ttk.Checkbutton(timed_switch, text="Vorher setzen", variable=self.switch_setup_before_var)
        switch_setup_check.grid(row=2, column=0, sticky="w", padx=8, pady=4)
        switch_end_off_check = ttk.Checkbutton(timed_switch, text="Am Ende aus", variable=self.switch_end_off_var)
        switch_end_off_check.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(timed_switch, text="Netzgerät-Modus").grid(row=2, column=2, sticky="w", padx=8, pady=4)
        switch_power_mode_combo = ttk.Combobox(timed_switch, textvariable=self.switch_power_mode_var, values=("Master", "Kanal"), width=8, state="readonly")
        switch_power_mode_combo.grid(row=2, column=3, sticky="ew", padx=8, pady=4)
        switch_preview_button = ttk.Button(timed_switch, text="Vorschau", command=self.preview_timed_switch)
        switch_preview_button.grid(row=2, column=4, sticky="ew", padx=8, pady=(4, 8))
        switch_start_button = ttk.Button(timed_switch, text="Schalten starten", command=self.start_timed_switch)
        switch_start_button.grid(row=3, column=4, sticky="ew", padx=8, pady=(4, 8))
        switch_stop_button = ttk.Button(timed_switch, text="Stop", command=self.stop_timed_switch)
        switch_stop_button.grid(row=3, column=5, sticky="ew", padx=8, pady=(4, 8))

        self._scope_widgets = [scope_value_button, measurement_combo, channel_spinbox, waveform_button, *waveform_checkbuttons, all_button, none_button, point_mode_combo]
        self._connection_widgets = [self.resource_combo, search_button, idn_button, address_entry]
        self._dmm_widgets = [dmm_value_button]
        self._vna_widgets = [sparameter_button, sparameter_format_combo, *sparameter_checkbuttons]
        self._screenshot_widgets = [screenshot_button]
        self._timed_widgets = [timed_dmm_button, timed_scope_button, timed_interval_entry, timed_count_entry]
        self._timed_dmm_widgets = [timed_dmm_button]
        self._timed_scope_widgets = [timed_scope_button]
        self._timed_stop_widgets = [timed_stop_button]
        self._generator_widgets = [
            generator_read_button,
            generator_set_button,
            generator_rf_off_button,
            generator_frequency_entry,
            generator_power_entry,
            generator_rf_combo,
            generator_max_power_entry,
            generator_rf_off_check,
        ]
        self._power_supply_widgets = [
            power_supply_read_button,
            power_supply_set_button,
            power_supply_output_off_button,
            power_supply_all_off_button,
            power_supply_channel_spinbox,
            power_supply_voltage_entry,
            power_supply_current_entry,
            power_supply_output_combo,
            power_supply_max_voltage_entry,
            power_supply_max_current_entry,
        ]
        self._power_supply_channel_spinbox = power_supply_channel_spinbox
        self._device_sections = {
            "scope": scope,
            "dmm": dmm,
            "timed": timed,
            "vna": vna,
            "generator": generator,
            "power_supply": power_supply,
        }
        self._sequence_widgets = [
            sequence_source_type_combo,
            sequence_generator_entry,
            sequence_generator_current_button,
            sequence_measurement_entry,
            sequence_measurement_current_button,
            sequence_start_entry,
            sequence_stop_entry,
            sequence_step_entry,
            sequence_power_entry,
            sequence_supply_channel_spinbox,
            sequence_voltage_start_entry,
            sequence_voltage_stop_entry,
            sequence_voltage_step_entry,
            sequence_current_limit_entry,
            sequence_settle_entry,
            sequence_mode_combo,
            sequence_rf_off_check,
            sequence_preview_button,
            sequence_start_button,
        ]
        self._sequence_stop_widgets = [sequence_stop_button]
        self._switch_widgets = [
            switch_source_combo,
            switch_address_entry,
            switch_current_button,
            switch_on_entry,
            switch_off_entry,
            switch_repetitions_entry,
            switch_setup_check,
            switch_end_off_check,
            switch_power_mode_combo,
            switch_preview_button,
            switch_start_button,
        ]
        self._switch_stop_widgets = [switch_stop_button]
        self._refresh_resource_combo()
        self._apply_saved_profile_for_address()

        self.log = tk.Text(log_frame, width=44, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.log.configure(yscrollcommand=scrollbar.set)

        status = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        self._apply_log_visibility()

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

    def read_signal_generator(self) -> None:
        self._run_worker("Signalgenerator-Einstellungen werden gelesen...", self._read_signal_generator)

    def set_signal_generator(self) -> None:
        try:
            self._generator_max_power()
        except ValueError as exc:
            messagebox.showerror("Signalgenerator", str(exc))
            return
        self._run_worker("Signalgenerator wird gesetzt...", self._set_signal_generator)

    def signal_generator_rf_off(self) -> None:
        self._run_worker("RF-Ausgang wird ausgeschaltet...", self._signal_generator_rf_off)

    def read_power_supply(self) -> None:
        self._run_worker("Netzgerät-Einstellungen werden gelesen...", self._read_power_supply)

    def set_power_supply(self) -> None:
        try:
            self._power_supply_limits()
        except ValueError as exc:
            messagebox.showerror("Netzgerät", str(exc))
            return
        self._run_worker("Netzgerät wird gesetzt...", self._set_power_supply)

    def power_supply_output_off(self) -> None:
        self._run_worker("Netzgerät-Kanal wird ausgeschaltet...", self._power_supply_output_off)

    def power_supply_all_outputs_off(self) -> None:
        self._run_worker("Alle Netzgerät-Ausgänge werden ausgeschaltet...", self._power_supply_all_outputs_off)

    def use_current_address_as_sequence_generator(self) -> None:
        self.sequence_generator_address_var.set(self.address_var.get().strip())

    def use_current_address_as_sequence_measurement(self) -> None:
        self.sequence_measurement_address_var.set(self.address_var.get().strip())

    def use_current_address_as_switch_source(self) -> None:
        self.switch_address_var.set(self.address_var.get().strip())

    def preview_sequence(self) -> None:
        try:
            config = self._sequence_config()
            message = self._sequence_preview_text(config)
        except ValueError as exc:
            messagebox.showerror("Ablauf-Vorschau", str(exc))
            return
        messagebox.showinfo("Ablauf-Vorschau", message)

    def preview_timed_switch(self) -> None:
        try:
            config = self._timed_switch_config()
            duration = config.repetitions * (config.on_s + config.off_s)
            message = (
                f"Quellgerät: {config.source_type}\n"
                f"Ereignisse: {config.repetitions * 2}\n"
                f"Geschätzte Dauer: {duration:.1f} s\n"
                f"ON/OFF: {config.on_s:.3f} s / {config.off_s:.3f} s\n"
                f"Vorher setzen: {'Ja' if config.setup_before_start else 'Nein'}\n"
                f"Am Ende aus: {'Ja' if config.end_off else 'Nein'}"
            )
        except ValueError as exc:
            messagebox.showerror("Schalt-Vorschau", str(exc))
            return
        messagebox.showinfo("Schalt-Vorschau", message)

    def start_sequence(self) -> None:
        if self.sequence_running:
            messagebox.showwarning("Automatischer Ablauf", "Es läuft bereits ein Ablauf.")
            return
        if self.timed_running:
            messagebox.showwarning("Automatischer Ablauf", "Bitte zuerst das getimte Messen stoppen.")
            return
        if self.switch_running:
            messagebox.showwarning("Automatischer Ablauf", "Bitte zuerst getimtes Schalten stoppen.")
            return
        try:
            config = self._sequence_config()
        except ValueError as exc:
            messagebox.showerror("Automatischer Ablauf", str(exc))
            return
        source_address = self.sequence_generator_address_var.get().strip()
        measurement_address = self.sequence_measurement_address_var.get().strip()
        self.sequence_stop_event.clear()
        self.sequence_running = True
        self._set_sequence_running(True)
        self.status_var.set("Automatischer Ablauf läuft...")
        self._append_log("Automatischer Ablauf läuft...")
        self.logger.info("Automatischer Ablauf läuft...")
        thread = threading.Thread(target=self._worker_target, args=(lambda: self._run_sequence(config, source_address, measurement_address),), daemon=True)
        thread.start()

    def stop_sequence(self) -> None:
        self.sequence_stop_event.set()
        self.status_var.set("Automatischer Ablauf wird gestoppt...")

    def start_timed_switch(self) -> None:
        if self.switch_running:
            messagebox.showwarning("Getimtes Schalten", "Es läuft bereits ein Schaltablauf.")
            return
        if self.sequence_running or self.timed_running:
            messagebox.showwarning("Getimtes Schalten", "Bitte zuerst laufende Abläufe stoppen.")
            return
        try:
            config = self._timed_switch_config()
        except ValueError as exc:
            messagebox.showerror("Getimtes Schalten", str(exc))
            return
        address = self.switch_address_var.get().strip()
        self.switch_stop_event.clear()
        self.switch_running = True
        self._set_switch_running(True)
        self.status_var.set("Getimtes Schalten läuft...")
        self._append_log("Getimtes Schalten läuft...")
        self.logger.info("Getimtes Schalten läuft...")
        thread = threading.Thread(target=self._worker_target, args=(lambda: self._run_timed_switch(config, address),), daemon=True)
        thread.start()

    def stop_timed_switch(self) -> None:
        self.switch_stop_event.set()
        self.status_var.set("Getimtes Schalten wird gestoppt...")

    def toggle_log(self) -> None:
        expanding = not self._log_visible
        self._last_controls_width = self._current_controls_width()
        if expanding:
            self._resize_window_for_log(expand=True, controls_width=self._last_controls_width)
        self._log_visible = not self._log_visible
        self._apply_log_visibility()
        if not expanding:
            self.after_idle(lambda: self._resize_window_for_log(expand=False, controls_width=self._last_controls_width))
        self.after_idle(self._restore_controls_width)

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
        if self.sequence_running or self.switch_running:
            messagebox.showwarning("Getimtes Messen", "Bitte zuerst laufende Abläufe stoppen.")
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

    def _read_signal_generator(self) -> str:
        with self._open_instrument() as instrument:
            info = instrument.info()
            settings = read_signal_generator_settings(instrument, info.idn)
        self._messages.put(("generator_settings", (settings.frequency, settings.power, settings.rf_output)))
        result = AcquisitionResult(kind="signal_generator", file_type="csv", content=_generator_settings_csv(settings.frequency, settings.power, settings.rf_output))
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Signal generator settings exported workbook=%s sheet=%s", export.workbook_path, export.sheet_name)
        return f"Signalgenerator gelesen: {export.workbook_path}\nFrequenz: {settings.frequency}\nPegel: {settings.power}\nRF: {settings.rf_output}"

    def _set_signal_generator(self) -> str:
        frequency = self.generator_frequency_var.get().strip()
        power = self.generator_power_var.get().strip()
        rf_enabled = self.generator_rf_var.get().strip().upper() == "ON"
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = set_signal_generator(
                instrument,
                info.idn,
                frequency,
                power,
                rf_enabled,
                self._generator_max_power(),
                self.generator_rf_off_before_change_var.get(),
            )
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Signal generator set exported workbook=%s sheet=%s frequency=%s power=%s rf=%s", export.workbook_path, export.sheet_name, frequency, power, rf_enabled)
        return f"Signalgenerator gesetzt: {export.workbook_path}\nFrequenz: {frequency}\nPegel: {power}\nRF: {'ON' if rf_enabled else 'OFF'}"

    def _signal_generator_rf_off(self) -> str:
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = set_signal_generator_rf_output(instrument, info.idn, False)
        self._messages.put(("generator_settings", (self.generator_frequency_var.get(), self.generator_power_var.get(), "OFF")))
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Signal generator RF off exported workbook=%s sheet=%s", export.workbook_path, export.sheet_name)
        return f"RF-Ausgang ausgeschaltet: {export.workbook_path}"

    def _read_power_supply(self) -> str:
        channel = self._power_supply_channel()
        with self._open_instrument() as instrument:
            info = instrument.info()
            settings = read_power_supply_settings(instrument, info.idn, channel)
        self._messages.put(("power_supply_settings", (settings.voltage_set, settings.current_set, settings.output_selected)))
        result = AcquisitionResult(kind="power_supply", file_type="csv", content=_power_supply_settings_csv(settings))
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Power supply settings exported workbook=%s sheet=%s", export.workbook_path, export.sheet_name)
        return (
            f"Netzgerät gelesen: {export.workbook_path}\nKanal: {settings.channel}\n"
            f"U set/ist: {settings.voltage_set} / {settings.voltage_measured}\nI set/ist: {settings.current_set} / {settings.current_measured}\nAusgang: {settings.output_selected}"
        )

    def _set_power_supply(self) -> str:
        channel = self._power_supply_channel()
        voltage = self.power_supply_voltage_var.get().strip()
        current = self.power_supply_current_var.get().strip()
        output_enabled = self.power_supply_output_var.get().strip().upper() == "ON"
        max_voltage, max_current = self._power_supply_limits()
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = set_power_supply(instrument, info.idn, channel, voltage, current, output_enabled, max_voltage, max_current)
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Power supply set exported workbook=%s sheet=%s channel=%s voltage=%s current=%s output=%s", export.workbook_path, export.sheet_name, channel, voltage, current, output_enabled)
        return f"Netzgerät gesetzt: {export.workbook_path}\nKanal: {channel}\nSpannung: {voltage}\nStromlimit: {current}\nAusgang: {'ON' if output_enabled else 'OFF'}"

    def _power_supply_output_off(self) -> str:
        channel = self._power_supply_channel()
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = set_power_supply_output(instrument, info.idn, channel, False)
        self._messages.put(("power_supply_settings", (self.power_supply_voltage_var.get(), self.power_supply_current_var.get(), "OFF")))
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Power supply output off exported workbook=%s sheet=%s channel=%s", export.workbook_path, export.sheet_name, channel)
        return f"Netzgerät-Kanal ausgeschaltet: {export.workbook_path}\nKanal: {channel}"

    def _power_supply_all_outputs_off(self) -> str:
        channel = self._power_supply_channel()
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = set_power_supply_master_output(instrument, info.idn, False, channel)
        self._messages.put(("power_supply_settings", (self.power_supply_voltage_var.get(), self.power_supply_current_var.get(), "OFF")))
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Power supply all outputs off exported workbook=%s sheet=%s", export.workbook_path, export.sheet_name)
        return f"Alle Netzgerät-Ausgänge ausgeschaltet: {export.workbook_path}"

    def _run_sequence(self, config: FrequencySweepConfig | VoltageSweepConfig, source_address: str, measurement_address: str) -> str:
        try:
            with VisaInstrument(source_address, timeout_ms=10000) as source, VisaInstrument(measurement_address, timeout_ms=10000) as measurement_instrument:
                if isinstance(config, VoltageSweepConfig):
                    sweep = run_voltage_sweep(
                        source,
                        measurement_instrument,
                        config,
                        stop_requested=self.sequence_stop_event.is_set,
                        progress=lambda message: self._messages.put(("progress", message)),
                    )
                    result = AcquisitionResult(kind="voltage sweep", file_type="csv", content=sweep.csv_content)
                    source_idn = sweep.power_supply_info.idn
                else:
                    sweep = run_frequency_sweep(
                        source,
                        measurement_instrument,
                        config,
                        stop_requested=self.sequence_stop_event.is_set,
                        progress=lambda message: self._messages.put(("progress", message)),
                    )
                    result = AcquisitionResult(kind="frequency sweep", file_type="csv", content=sweep.csv_content)
                    source_idn = sweep.generator_info.idn
            export = append_result(self._output_path(), source_address, source_idn, result)
            stopped_text = " gestoppt" if sweep.stopped else " abgeschlossen"
            self.logger.info(
                "Automatic sweep exported workbook=%s sheet=%s kind=%s points=%s ok=%s errors=%s source=%s measurement=%s",
                export.workbook_path,
                export.sheet_name,
                result.kind,
                sweep.actual_count,
                sweep.ok_count,
                sweep.error_count,
                source_address,
                measurement_address,
            )
            return f"Automatischer Ablauf{stopped_text}: {export.workbook_path}\nTabellenblatt: {export.sheet_name}\nMesspunkte: {sweep.actual_count}\nOK: {sweep.ok_count}, Fehler: {sweep.error_count}"
        finally:
            self.sequence_running = False
            self._messages.put(("sequence_done", ""))

    def _run_timed_switch(self, config: TimedSwitchConfig, address: str) -> str:
        try:
            with VisaInstrument(address, timeout_ms=10000) as source:
                result_data = run_timed_switch(
                    source,
                    config,
                    stop_requested=self.switch_stop_event.is_set,
                    progress=lambda message: self._messages.put(("progress", message)),
                )
            result = AcquisitionResult(kind="timed switch", file_type="csv", content=result_data.csv_content)
            export = append_result(self._output_path(), address, result_data.source_info.idn, result)
            stopped_text = " gestoppt" if result_data.stopped else " abgeschlossen"
            self.logger.info(
                "Timed switch exported workbook=%s sheet=%s events=%s ok=%s errors=%s source=%s",
                export.workbook_path,
                export.sheet_name,
                result_data.actual_count,
                result_data.ok_count,
                result_data.error_count,
                address,
            )
            return f"Getimtes Schalten{stopped_text}: {export.workbook_path}\nTabellenblatt: {export.sheet_name}\nEreignisse: {result_data.actual_count}\nOK: {result_data.ok_count}, Fehler: {result_data.error_count}"
        finally:
            self.switch_running = False
            self._messages.put(("switch_done", ""))

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

    def _generator_max_power(self) -> float:
        try:
            return float(self.generator_max_power_var.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Max. Pegel muss eine Zahl in dBm sein.") from exc

    def _power_supply_limits(self) -> tuple[float, float]:
        try:
            max_voltage = float(self.power_supply_max_voltage_var.get().replace(",", "."))
            max_current = float(self.power_supply_max_current_var.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Max. V und Max. A müssen Zahlen sein.") from exc
        if max_voltage <= 0 or max_current <= 0:
            raise ValueError("Max. V und Max. A müssen größer als 0 sein.")
        return max_voltage, max_current

    def _power_supply_channel(self) -> int:
        try:
            channel = int(self.power_supply_channel_var.get())
        except (ValueError, tk.TclError) as exc:
            raise ValueError("Netzgerät-Kanal muss eine ganze Zahl sein.") from exc
        max_channel = hmp_channel_count(self.current_profile.model_family if self.current_profile.supports_power_supply else "")
        if channel < 1 or channel > max_channel:
            raise ValueError(f"Netzgerät-Kanal muss zwischen 1 und {max_channel} liegen.")
        return channel

    def _sequence_config(self) -> FrequencySweepConfig | VoltageSweepConfig:
        source_address = self.sequence_generator_address_var.get().strip()
        measurement_address = self.sequence_measurement_address_var.get().strip()
        if not source_address:
            raise ValueError("Bitte Quellgerät-Adresse eintragen.")
        if not measurement_address:
            raise ValueError("Bitte Messgerät-Adresse eintragen.")
        try:
            settle_s = float(self.sequence_settle_var.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Wartezeit muss eine Zahl in Sekunden sein.") from exc
        if settle_s < 0:
            raise ValueError("Wartezeit darf nicht negativ sein.")
        measurement_mode = "scope" if self.sequence_measurement_mode_var.get().strip().lower() == "scope" else "dmm"

        if self.sequence_source_type_var.get().strip().lower() == "netzgerät":
            voltage_points(self.sequence_start_voltage_var.get(), self.sequence_stop_voltage_var.get(), self.sequence_step_voltage_var.get())
            stop_voltage = parse_voltage(self.sequence_stop_voltage_var.get())
            current_limit = parse_ampere(self.sequence_current_limit_var.get())
            max_voltage, max_current = self._power_supply_limits()
            if stop_voltage > max_voltage:
                raise ValueError(f"Stopspannung {stop_voltage:g} V überschreitet Max. V {max_voltage:g} V.")
            if current_limit > max_current:
                raise ValueError(f"Stromlimit {current_limit:g} A überschreitet Max. A {max_current:g} A.")
            return VoltageSweepConfig(
                start_voltage=self.sequence_start_voltage_var.get().strip(),
                stop_voltage=self.sequence_stop_voltage_var.get().strip(),
                step_voltage=self.sequence_step_voltage_var.get().strip(),
                current_limit=self.sequence_current_limit_var.get().strip(),
                channel=self._sequence_supply_channel(),
                max_voltage=max_voltage,
                max_current=max_current,
                settle_s=settle_s,
                measurement_mode=measurement_mode,
                scope_measurement=self.measurement_var.get(),
                scope_channel=self.channel_var.get(),
                output_off_at_end=self.sequence_rf_off_at_end_var.get(),
            )

        frequency_points(self.sequence_start_frequency_var.get(), self.sequence_stop_frequency_var.get(), self.sequence_step_frequency_var.get())
        power_dbm = parse_dbm(self.sequence_power_var.get())
        max_power_dbm = self._generator_max_power()
        if power_dbm > max_power_dbm:
            raise ValueError(f"Pegel {power_dbm:g} dBm überschreitet Max. Pegel {max_power_dbm:g} dBm.")
        return FrequencySweepConfig(
            start_frequency=self.sequence_start_frequency_var.get().strip(),
            stop_frequency=self.sequence_stop_frequency_var.get().strip(),
            step_frequency=self.sequence_step_frequency_var.get().strip(),
            power=self.sequence_power_var.get().strip(),
            max_power_dbm=max_power_dbm,
            settle_s=settle_s,
            measurement_mode=measurement_mode,
            scope_measurement=self.measurement_var.get(),
            scope_channel=self.channel_var.get(),
            rf_off_before_change=self.generator_rf_off_before_change_var.get(),
            rf_off_at_end=self.sequence_rf_off_at_end_var.get(),
        )

    def _sequence_supply_channel(self) -> int:
        try:
            channel = int(self.sequence_supply_channel_var.get())
        except (ValueError, tk.TclError) as exc:
            raise ValueError("Ablauf-Netzteil-Kanal muss eine ganze Zahl sein.") from exc
        if channel < 1 or channel > 4:
            raise ValueError("Ablauf-Netzteil-Kanal muss zwischen 1 und 4 liegen.")
        return channel

    def _sequence_preview_text(self, config: FrequencySweepConfig | VoltageSweepConfig) -> str:
        if isinstance(config, VoltageSweepConfig):
            points = voltage_points(config.start_voltage, config.stop_voltage, config.step_voltage)
            duration = len(points) * config.settle_s
            return (
                "Typ: Netzgerät-Spannungs-Sweep\n"
                f"Punkte: {len(points)}\n"
                f"Geschätzte Mindestdauer: {duration:.1f} s\n"
                f"Start/Stop/Schritt: {config.start_voltage} / {config.stop_voltage} / {config.step_voltage}\n"
                f"Kanal: {config.channel}\n"
                f"Stromlimit: {config.current_limit}\n"
                f"Ende aus: {'Ja' if config.output_off_at_end else 'Nein'}"
            )
        points = frequency_points(config.start_frequency, config.stop_frequency, config.step_frequency)
        duration = len(points) * config.settle_s
        return (
            "Typ: Signalgenerator-Frequenz-Sweep\n"
            f"Punkte: {len(points)}\n"
            f"Geschätzte Mindestdauer: {duration:.1f} s\n"
            f"Start/Stop/Schritt: {config.start_frequency} / {config.stop_frequency} / {config.step_frequency}\n"
            f"Pegel: {config.power}\n"
            f"Ende aus: {'Ja' if config.rf_off_at_end else 'Nein'}"
        )

    def _timed_switch_config(self) -> TimedSwitchConfig:
        if not self.switch_address_var.get().strip():
            raise ValueError("Bitte Schalt-Quelladresse eintragen.")
        try:
            on_s = float(self.switch_on_s_var.get().replace(",", "."))
            off_s = float(self.switch_off_s_var.get().replace(",", "."))
            repetitions = int(self.switch_repetitions_var.get())
        except ValueError as exc:
            raise ValueError("ON/OFF-Dauer müssen Zahlen und Wiederholungen eine ganze Zahl sein.") from exc
        source_type = "power_supply" if self.switch_source_type_var.get().strip().lower() == "netzgerät" else "generator"
        if source_type == "generator":
            return TimedSwitchConfig(
                source_type=source_type,
                on_s=on_s,
                off_s=off_s,
                repetitions=repetitions,
                end_off=self.switch_end_off_var.get(),
                setup_before_start=self.switch_setup_before_var.get(),
                generator_frequency=self.generator_frequency_var.get().strip(),
                generator_power=self.generator_power_var.get().strip(),
                generator_max_power_dbm=self._generator_max_power(),
            )
        max_voltage, max_current = self._power_supply_limits()
        return TimedSwitchConfig(
            source_type=source_type,
            on_s=on_s,
            off_s=off_s,
            repetitions=repetitions,
            end_off=self.switch_end_off_var.get(),
            setup_before_start=self.switch_setup_before_var.get(),
            power_supply_channel=self._power_supply_channel() if self.current_profile.supports_power_supply else self._safe_power_supply_channel_setting(),
            power_supply_voltage=self.power_supply_voltage_var.get().strip(),
            power_supply_current=self.power_supply_current_var.get().strip(),
            power_supply_max_voltage=max_voltage,
            power_supply_max_current=max_current,
            power_supply_switch_mode="channel" if self.switch_power_mode_var.get().strip().lower() == "kanal" else "master",
        )

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
            elif kind == "generator_settings":
                if isinstance(message, tuple) and len(message) == 3:
                    frequency, power, rf_output = message
                    self.generator_frequency_var.set(str(frequency))
                    self.generator_power_var.set(str(power))
                    self.generator_rf_var.set(str(rf_output) if str(rf_output) in {"ON", "OFF"} else "OFF")
            elif kind == "power_supply_settings":
                if isinstance(message, tuple) and len(message) == 3:
                    voltage, current, output = message
                    self.power_supply_voltage_var.set(str(voltage))
                    self.power_supply_current_var.set(str(current))
                    self.power_supply_output_var.set(str(output) if str(output) in {"ON", "OFF"} else "OFF")
            elif kind == "progress":
                if isinstance(message, str):
                    self.status_var.set(message)
                    self._append_log(message)
            elif kind == "timed_done":
                self._set_timed_running(False)
            elif kind == "sequence_done":
                self._set_sequence_running(False)
            elif kind == "switch_done":
                self._set_switch_running(False)
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

    def _scroll_controls_if_needed(self, canvas: tk.Canvas, event: tk.Event) -> None:
        scrollregion = canvas.bbox("all")
        if scrollregion is None:
            return
        content_height = scrollregion[3] - scrollregion[1]
        if content_height <= canvas.winfo_height():
            canvas.yview_moveto(0)
            return
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _apply_log_visibility(self) -> None:
        if self._main_pane is None or self._log_frame is None or self._log_pane is None:
            return
        if self._log_visible:
            if self._collapsed_log_button is not None:
                self._collapsed_log_button.grid_remove()
            self._log_pane.grid(row=0, column=1, sticky="nsew")
            self._log_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 8), pady=4)
            self._log_toggle_var.set("›")
        else:
            self._log_pane.grid_remove()
            if self._collapsed_log_button is not None:
                self._collapsed_log_button.grid(row=0, column=1, sticky="ns", padx=(2, 4), pady=4)
            self._log_toggle_var.set("‹")

    def _resize_window_for_log(self, expand: bool, controls_width: int | None) -> None:
        try:
            geometry = self.geometry()
            size, *position = geometry.split("+")
            width_text, height_text = size.split("x", 1)
            height = int(height_text)
        except ValueError:
            return
        controls_width = controls_width or self._current_controls_width()
        side_width = 430 if expand else 42
        target_width = max(self.minsize()[0], controls_width + side_width)
        suffix = "+" + "+".join(position) if position else ""
        self.geometry(f"{target_width}x{height}{suffix}")

    def _current_controls_width(self) -> int:
        if self._controls_container is None:
            return max(1, self.winfo_width() - 430)
        width = self._controls_container.winfo_width()
        return width if width > 1 else max(1, self.winfo_width() - 430)

    def _restore_controls_width(self) -> None:
        return

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
        generator_enabled = profile.supports_signal_generator
        power_supply_enabled = profile.supports_power_supply
        if power_supply_enabled:
            max_channel = hmp_channel_count(profile.model_family)
            if self._power_supply_channel_spinbox is not None:
                self._power_supply_channel_spinbox.configure(to=max_channel)
            try:
                current_channel = int(self.power_supply_channel_var.get())
            except (ValueError, tk.TclError):
                current_channel = 1
            if current_channel > max_channel:
                self.power_supply_channel_var.set(max_channel)
            elif current_channel < 1:
                self.power_supply_channel_var.set(1)
        self._set_section_visible("scope", scope_enabled)
        self._set_section_visible("dmm", dmm_enabled)
        self._set_section_visible("timed", timed_enabled)
        self._set_section_visible("vna", vna_enabled)
        self._set_section_visible("generator", generator_enabled)
        self._set_section_visible("power_supply", power_supply_enabled)
        self._set_widgets_enabled(self._scope_widgets, scope_enabled)
        self._set_widgets_enabled(self._dmm_widgets, dmm_enabled)
        self._set_widgets_enabled(self._timed_widgets, timed_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_dmm_widgets, dmm_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_scope_widgets, scope_measurement_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_stop_widgets, self.timed_running)
        self._set_widgets_enabled(self._vna_widgets, vna_enabled)
        self._set_widgets_enabled(self._screenshot_widgets, screenshot_enabled)
        self._set_widgets_enabled(self._generator_widgets, generator_enabled)
        self._set_widgets_enabled(self._power_supply_widgets, power_supply_enabled)
        if self.sequence_running:
            self._set_sequence_running(True)
        if self.switch_running:
            self._set_switch_running(True)

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
            "supports_signal_generator": profile.supports_signal_generator,
            "supports_power_supply": profile.supports_power_supply,
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
            supports_signal_generator=bool(saved.get("supports_signal_generator", False)),
            supports_power_supply=bool(saved.get("supports_power_supply", False)),
        )

    def _set_timed_running(self, running: bool) -> None:
        self.timed_running = running
        scope_enabled = self.current_profile.supports_scope_measurements
        dmm_enabled = self.current_profile.supports_dmm_read
        self._set_widgets_enabled(self._timed_widgets, (scope_enabled or dmm_enabled) and not running)
        self._set_widgets_enabled(self._timed_dmm_widgets, dmm_enabled and not running)
        self._set_widgets_enabled(self._timed_scope_widgets, scope_enabled and not running)
        self._set_widgets_enabled(self._timed_stop_widgets, running)
        self._set_widgets_enabled(self._sequence_widgets, not running and not self.sequence_running and not self.switch_running)
        self._set_widgets_enabled(self._sequence_stop_widgets, False)
        self._set_widgets_enabled(self._switch_widgets, not running and not self.sequence_running and not self.switch_running)
        self._set_widgets_enabled(self._switch_stop_widgets, False)

    def _set_sequence_running(self, running: bool) -> None:
        self.sequence_running = running
        self._set_widgets_enabled(self._sequence_widgets, not running)
        self._set_widgets_enabled(self._sequence_stop_widgets, running)
        self._set_widgets_enabled(self._switch_widgets, not running)
        self._set_widgets_enabled(self._switch_stop_widgets, False)
        self._set_widgets_enabled(self._connection_widgets, not running)
        if running:
            self._set_widgets_enabled(self._scope_widgets, False)
            self._set_widgets_enabled(self._dmm_widgets, False)
            self._set_widgets_enabled(self._timed_widgets, False)
            self._set_widgets_enabled(self._timed_dmm_widgets, False)
            self._set_widgets_enabled(self._timed_scope_widgets, False)
            self._set_widgets_enabled(self._vna_widgets, False)
            self._set_widgets_enabled(self._screenshot_widgets, False)
            self._set_widgets_enabled(self._generator_widgets, False)
            self._set_widgets_enabled(self._power_supply_widgets, False)
        else:
            self._apply_profile(self.current_profile)
            self._set_widgets_enabled(self._sequence_widgets, True)
            self._set_widgets_enabled(self._sequence_stop_widgets, False)
            self._set_widgets_enabled(self._switch_widgets, True)
            self._set_widgets_enabled(self._switch_stop_widgets, False)

    def _set_switch_running(self, running: bool) -> None:
        self.switch_running = running
        self._set_widgets_enabled(self._switch_widgets, not running)
        self._set_widgets_enabled(self._switch_stop_widgets, running)
        self._set_widgets_enabled(self._sequence_widgets, not running)
        self._set_widgets_enabled(self._sequence_stop_widgets, False)
        self._set_widgets_enabled(self._connection_widgets, not running)
        if running:
            self._set_widgets_enabled(self._scope_widgets, False)
            self._set_widgets_enabled(self._dmm_widgets, False)
            self._set_widgets_enabled(self._timed_widgets, False)
            self._set_widgets_enabled(self._timed_dmm_widgets, False)
            self._set_widgets_enabled(self._timed_scope_widgets, False)
            self._set_widgets_enabled(self._vna_widgets, False)
            self._set_widgets_enabled(self._screenshot_widgets, False)
            self._set_widgets_enabled(self._generator_widgets, False)
            self._set_widgets_enabled(self._power_supply_widgets, False)
        else:
            self._apply_profile(self.current_profile)
            self._set_widgets_enabled(self._switch_widgets, True)
            self._set_widgets_enabled(self._switch_stop_widgets, False)
            self._set_widgets_enabled(self._sequence_widgets, True)
            self._set_widgets_enabled(self._sequence_stop_widgets, False)

    def _set_widgets_enabled(self, widgets: list[tk.Widget], enabled: bool) -> None:
        for widget in widgets:
            state = "readonly" if enabled and widget.winfo_class() == "TCombobox" else "normal" if enabled else "disabled"
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass

    def _set_section_visible(self, section: str, visible: bool) -> None:
        widget = self._device_sections.get(section)
        if widget is None:
            return
        if visible:
            widget.grid()
        else:
            widget.grid_remove()

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
            "log_visible": self._log_visible,
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
            "generator_frequency": self.generator_frequency_var.get(),
            "generator_power": self.generator_power_var.get(),
            "generator_rf": self.generator_rf_var.get(),
            "generator_max_power": self.generator_max_power_var.get(),
            "generator_rf_off_before_change": self.generator_rf_off_before_change_var.get(),
            "power_supply_channel": self._safe_power_supply_channel_setting(),
            "power_supply_voltage": self.power_supply_voltage_var.get(),
            "power_supply_current": self.power_supply_current_var.get(),
            "power_supply_output": self.power_supply_output_var.get(),
            "power_supply_max_voltage": self.power_supply_max_voltage_var.get(),
            "power_supply_max_current": self.power_supply_max_current_var.get(),
            "sequence_source_type": self.sequence_source_type_var.get(),
            "sequence_generator_address": self.sequence_generator_address_var.get().strip(),
            "sequence_measurement_address": self.sequence_measurement_address_var.get().strip(),
            "sequence_start_frequency": self.sequence_start_frequency_var.get(),
            "sequence_stop_frequency": self.sequence_stop_frequency_var.get(),
            "sequence_step_frequency": self.sequence_step_frequency_var.get(),
            "sequence_power": self.sequence_power_var.get(),
            "sequence_supply_channel": self._safe_sequence_supply_channel_setting(),
            "sequence_start_voltage": self.sequence_start_voltage_var.get(),
            "sequence_stop_voltage": self.sequence_stop_voltage_var.get(),
            "sequence_step_voltage": self.sequence_step_voltage_var.get(),
            "sequence_current_limit": self.sequence_current_limit_var.get(),
            "sequence_settle": self.sequence_settle_var.get(),
            "sequence_measurement_mode": self.sequence_measurement_mode_var.get(),
            "sequence_rf_off_at_end": self.sequence_rf_off_at_end_var.get(),
            "switch_source_type": self.switch_source_type_var.get(),
            "switch_address": self.switch_address_var.get().strip(),
            "switch_on_s": self.switch_on_s_var.get(),
            "switch_off_s": self.switch_off_s_var.get(),
            "switch_repetitions": self.switch_repetitions_var.get(),
            "switch_setup_before": self.switch_setup_before_var.get(),
            "switch_end_off": self.switch_end_off_var.get(),
            "switch_power_mode": self.switch_power_mode_var.get(),
            "devices": self.saved_devices,
        }
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def _safe_power_supply_channel_setting(self) -> int:
        try:
            return int(self.power_supply_channel_var.get())
        except (ValueError, tk.TclError):
            return 1

    def _safe_sequence_supply_channel_setting(self) -> int:
        try:
            return int(self.sequence_supply_channel_var.get())
        except (ValueError, tk.TclError):
            return 1

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


def _generator_settings_csv(frequency: str, power: str, rf_output: str) -> str:
    return _csv_rows([["Setting", "Value"], ["Frequency", frequency], ["Power", power], ["RFOutput", rf_output]])


def _power_supply_settings_csv(settings) -> str:
    return _csv_rows(
        [
            ["Setting", "Value"],
            ["Channel", settings.channel],
            ["VoltageSet", settings.voltage_set],
            ["CurrentSet", settings.current_set],
            ["VoltageMeasured", settings.voltage_measured],
            ["CurrentMeasured", settings.current_measured],
            ["OutputSelected", settings.output_selected],
            ["OutputGeneral", settings.output_general],
        ]
    )




if __name__ == "__main__":
    raise SystemExit(main())
