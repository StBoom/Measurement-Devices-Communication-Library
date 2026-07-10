from __future__ import annotations

import csv
import json
import os
import queue
import threading
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from io import StringIO
from pathlib import Path
from time import monotonic, sleep
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
from .picoscope_client import list_picoscope_resources
from .saleae_client import list_saleae_resources
from .sequence import (
    CustomSequenceConfig,
    DataLogger34970AConfig,
    FrequencySweepConfig,
    SequenceStep,
    SequenceVariable,
    TimedSwitchConfig,
    VoltageSweepConfig,
    create_sequence_instrument,
    frequency_points,
    list_direct_serial_ports,
    parse_json_bool,
    parse_ampere,
    parse_dbm,
    parse_voltage,
    probe_direct_serial_idn,
    read_34970a_data_logger,
    read_34970a_measurement_plan,
    parse_34970a_measurement_plan,
    run_frequency_sweep,
    run_custom_sequence,
    run_timed_switch,
    run_voltage_sweep,
    set_preferred_serial_scpi_settings,
    voltage_points,
)
from .visa_client import VisaInstrument, list_resources


DEFAULT_ADDRESS = "USB0::0x0957::0x1796::MY58104189::0::INSTR"
SETTINGS_PATH = Path("gui_settings.json")
SCOPE_MEASUREMENTS = ("Vpp", "Vrms", "Frequency", "Period", "Vmax", "Vmin")
ON_OFF_VALUES = ("ON", "OFF")
CHANNEL_VALUES = ("1", "2", "3", "4")
POINT_MODE_VALUES = ("RAW", "NORMAL", "MAXIMUM")
PICOSCOPE_RANGE_VALUES = ("100MV", "200MV", "500MV", "1V", "2V", "5V", "10V", "20V")
DATA_LOGGER_34970A_MEASUREMENTS = ("VOLT_DC", "RES", "FRES", "CURR_DC", "TEMP")
CUSTOM_SEQUENCE_ACTIONS = (
    ("Signalgenerator: Frequenz setzen", "generator_set_frequency", ("device", "frequency", "power", "max_power_dbm", "rf")),
    ("Signalgenerator: Pegel setzen", "generator_set_power", ("device", "power", "max_power_dbm", "rf", "rf_off_before_change")),
    ("Signalgenerator: RF ein/aus", "generator_rf", ("device", "enabled")),
    ("Netzgerät: Spannung/Strom setzen", "power_supply_set", ("device", "voltage", "current", "channel", "output")),
    ("Netzgerät: Kanal ein/aus", "power_supply_output", ("device", "enabled", "channel")),
    ("Netzgerät: Master ein/aus", "power_supply_master_output", ("device", "enabled", "channel")),
    ("Multimeter: Messwert lesen", "dmm_read", ("device",)),
    ("Oszilloskop: Messwert lesen", "scope_measure", ("device", "measurement", "channel")),
    ("Oszilloskop/Spektrum: Kurve erfassen", "capture_waveform", ("device", "channels", "point_mode")),
    ("Screenshot erfassen", "capture_screenshot", ("device",)),
    ("Seriellen Log aufzeichnen", "serial_log", ("device", "duration_s", "baudrate", "serial_format")),
    ("Parallel-Messphase", "parallel_phase", ("device", "duration_s", "interval_s", "tasks")),
    ("PicoScope: Analog erfassen", "picoscope_analog", ("device", "channels", "range", "samples", "interval_us")),
    ("PicoScope: Digital erfassen", "picoscope_digital", ("device", "channels", "logic_level_mv", "samples", "interval_us")),
    ("Agilent 34970A: Kanäle messen", "data_logger_34970a_read", ("device", "measurement", "channels", "baudrate", "serial_format")),
    ("Agilent 34970A: Messplan", "data_logger_34970a_plan", ("device", "plan", "baudrate", "serial_format")),
    ("Saleae: Digital aufnehmen", "saleae_capture", ("device", "channels", "duration_s", "sample_rate", "threshold_v")),
    ("Saleae: UART dekodieren", "saleae_uart", ("device", "channel", "baudrate", "duration_s", "sample_rate")),
    ("Saleae: I2C dekodieren", "saleae_i2c", ("device", "sda", "scl", "duration_s", "sample_rate")),
    ("Saleae: SPI dekodieren", "saleae_spi", ("device", "mosi", "miso", "clock", "duration_s")),
    ("Saleae: CAN dekodieren", "saleae_can", ("device", "channel", "bitrate", "duration_s", "sample_rate")),
    ("Warten", "wait", ("device", "seconds")),
)
CUSTOM_SEQUENCE_FILE_VERSION = 1
CUSTOM_SEQUENCE_EXAMPLES = (
    ("Multimeter getimt", "timed_dmm"),
    ("Oszilloskop getimt", "timed_scope"),
    ("RF schalten", "rf_switch"),
    ("Signalgenerator + Multimeter", "generator_dmm"),
    ("Signalgenerator + Oszilloskop", "generator_scope"),
    ("Signalgenerator + Spektrumanalysator", "generator_spectrum"),
    ("Netzgerät + Multimeter", "supply_dmm"),
    ("Netzgerät + Oszilloskop", "supply_scope"),
    ("Netzgerät schalten", "supply_switch"),
)
SEQUENCE_DEVICE_ROLES = ("Multimeter", "Netzgerät", "Oszilloskop", "Signalgenerator", "Spektrumanalysator", "Netzwerkanalysator", "Seriell", "PicoScope", "Saleae", "Datenlogger", "Gerät")
SERIAL_FORMAT_VALUES = ("8N1", "7E1", "7O1", "8E1", "8O1", "8N2")


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
        self.data_logger_34970a_measurement_var = tk.StringVar(value=self.settings.get("data_logger_34970a_measurement", "TEMP"))
        self.data_logger_34970a_channels_var = tk.StringVar(value=self.settings.get("data_logger_34970a_channels", "1-20"))
        self.data_logger_34970a_plan_var = tk.StringVar(value=self.settings.get("data_logger_34970a_plan", "1-20:TEMP; 21-22:CURR_DC"))
        self.data_logger_34970a_baudrate_var = tk.StringVar(value=str(self.settings.get("data_logger_34970a_baudrate", "19200")))
        self.data_logger_34970a_serial_format_var = tk.StringVar(value=self.settings.get("data_logger_34970a_serial_format", "8N1"))
        self.data_logger_34970a_interval_var = tk.StringVar(value=str(self.settings.get("data_logger_34970a_interval", "5")))
        self.data_logger_34970a_count_var = tk.StringVar(value=str(self.settings.get("data_logger_34970a_count", "0")))
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
        self.custom_sequence_steps: list[SequenceStep] = [self._step_from_settings(step) for step in self.settings.get("custom_sequence_steps", []) if isinstance(step, dict)]
        self.custom_sequence_devices: dict[str, str] = {str(name): str(address) for name, address in self.settings.get("custom_sequence_devices", {}).items()} if isinstance(self.settings.get("custom_sequence_devices", {}), dict) else {}
        self.custom_sequence_repeat_var = tk.StringVar(value=str(self.settings.get("custom_sequence_repeat", "1")))
        self.custom_sequence_pause_var = tk.StringVar(value=str(self.settings.get("custom_sequence_pause", "0")))
        self.custom_sequence_variable_name_var = tk.StringVar(value=self.settings.get("custom_sequence_variable_name", "frequency"))
        self.custom_sequence_variable_unit_var = tk.StringVar(value=self.settings.get("custom_sequence_variable_unit", "frequency"))
        self.custom_sequence_variable_start_var = tk.StringVar(value=self.settings.get("custom_sequence_variable_start", "100 MHz"))
        self.custom_sequence_variable_step_var = tk.StringVar(value=self.settings.get("custom_sequence_variable_step", "1 MHz"))
        self.custom_sequence_end_rf_off_var = tk.BooleanVar(value=bool(self.settings.get("custom_sequence_end_rf_off", True)))
        self.custom_sequence_end_supply_off_var = tk.BooleanVar(value=bool(self.settings.get("custom_sequence_end_supply_off", False)))
        self.custom_sequence_window: tk.Toplevel | None = None
        self.custom_sequence_tree: ttk.Treeview | None = None
        self.custom_sequence_device_tree: ttk.Treeview | None = None
        self.custom_sequence_device_select_var: tk.StringVar | None = None
        self.custom_sequence_device_select_combo: ttk.Combobox | None = None
        self.custom_sequence_device_select_map: dict[str, str] = {}
        self.custom_sequence_serial_port_var: tk.StringVar | None = None
        self.custom_sequence_serial_port_combo: ttk.Combobox | None = None
        self.custom_sequence_serial_port_map: dict[str, str] = {}
        self.custom_sequence_device_name_var: tk.StringVar | None = None
        self.custom_sequence_device_address_var: tk.StringVar | None = None
        self.custom_sequence_device_role_var: tk.StringVar | None = None
        self.custom_sequence_action_var: tk.StringVar | None = None
        self.custom_sequence_example_var: tk.StringVar | None = None
        self.custom_sequence_param_vars: dict[str, tk.StringVar] = {}
        self.custom_sequence_param_labels: dict[str, ttk.Label] = {}
        self.custom_sequence_param_widgets: dict[str, tk.Widget] = {}
        self.custom_sequence_edit_index: int | None = None
        self.custom_sequence_step_button: ttk.Button | None = None
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
        self._data_logger_widgets: list[tk.Widget] = []
        self._data_logger_stop_widgets: list[tk.Widget] = []
        self._spectrum_widgets: list[tk.Widget] = []
        self._spectrum_screenshot_widgets: list[tk.Widget] = []
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
        self._custom_sequence_widgets: list[tk.Widget] = []
        self._device_sections: dict[str, tk.Widget] = {}
        self._power_supply_channel_spinbox: ttk.Spinbox | None = None
        self.timed_stop_event = threading.Event()
        self.operation_stop_event = threading.Event()
        self.sequence_stop_event = threading.Event()
        self.switch_stop_event = threading.Event()
        self.timed_running = False
        self.operation_running = False
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

        scope = ttk.LabelFrame(measurement_area, text="Oszilloskop")
        scope.grid(row=0, column=0, sticky="ew")

        scope_measurement = ttk.Frame(scope)
        scope_measurement.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        scope_value_button = ttk.Button(scope_measurement, text="Scope Messwert", command=self.read_scope_measurement)
        scope_value_button.pack(side="left", padx=(0, 8))
        ttk.Label(scope_measurement, text="Messung").pack(side="left", padx=(0, 4))
        measurement_combo = ttk.Combobox(
            scope_measurement,
            textvariable=self.measurement_var,
            values=SCOPE_MEASUREMENTS,
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
            values=POINT_MODE_VALUES,
            width=10,
            state="readonly",
        )
        point_mode_combo.pack(side="left", padx=(0, 8))

        dmm = ttk.LabelFrame(measurement_area, text="Multimeter")
        dmm.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        dmm_value_button = ttk.Button(dmm, text="DMM Messwert", command=self.read_value)
        dmm_value_button.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Label(dmm, text="Für Geräte mit :READ? Unterstützung").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))

        timed = ttk.LabelFrame(measurement_area, text="Getimtes Messen")
        timed.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        timed.grid_remove()

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
        vna.grid(row=3, column=0, sticky="ew", pady=(12, 0))

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

        data_logger = ttk.LabelFrame(measurement_area, text="34970A Datenlogger")
        data_logger.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        data_logger.columnconfigure(0, weight=1)
        data_logger_controls = ttk.Frame(data_logger)
        data_logger_controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        data_logger_read_button = ttk.Button(data_logger_controls, text="Kanäle messen", command=self.read_data_logger_34970a)
        data_logger_read_button.pack(side="left", padx=(0, 8))
        ttk.Label(data_logger_controls, text="Messart").pack(side="left", padx=(0, 4))
        data_logger_measurement_combo = ttk.Combobox(data_logger_controls, textvariable=self.data_logger_34970a_measurement_var, values=DATA_LOGGER_34970A_MEASUREMENTS, width=10, state="readonly")
        data_logger_measurement_combo.pack(side="left", padx=(0, 8))
        ttk.Label(data_logger_controls, text="Kanäle").pack(side="left", padx=(0, 4))
        data_logger_channels_entry = ttk.Entry(data_logger_controls, textvariable=self.data_logger_34970a_channels_var, width=12)
        data_logger_channels_entry.pack(side="left", padx=(0, 8))
        ttk.Label(data_logger_controls, text="Baud").pack(side="left", padx=(0, 4))
        data_logger_baudrate_entry = ttk.Entry(data_logger_controls, textvariable=self.data_logger_34970a_baudrate_var, width=7)
        data_logger_baudrate_entry.pack(side="left", padx=(0, 8))
        ttk.Label(data_logger_controls, text="Format").pack(side="left", padx=(0, 4))
        data_logger_serial_format_combo = ttk.Combobox(data_logger_controls, textvariable=self.data_logger_34970a_serial_format_var, values=SERIAL_FORMAT_VALUES, width=6, state="readonly")
        data_logger_serial_format_combo.pack(side="left", padx=(0, 8))

        data_logger_plan = ttk.Frame(data_logger)
        data_logger_plan.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        data_logger_plan.columnconfigure(2, weight=1)
        data_logger_plan_button = ttk.Button(data_logger_plan, text="Messplan messen", command=self.read_data_logger_34970a_plan)
        data_logger_plan_button.grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(data_logger_plan, text="Plan").grid(row=0, column=1, sticky="w", padx=(0, 4))
        data_logger_plan_entry = ttk.Entry(data_logger_plan, textvariable=self.data_logger_34970a_plan_var)
        data_logger_plan_entry.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        data_logger_timing = ttk.Frame(data_logger)
        data_logger_timing.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(data_logger_timing, text="Intervall [s]").pack(side="left", padx=(0, 4))
        data_logger_interval_entry = ttk.Entry(data_logger_timing, textvariable=self.data_logger_34970a_interval_var, width=8)
        data_logger_interval_entry.pack(side="left", padx=(0, 8))
        ttk.Label(data_logger_timing, text="Anzahl (0=endlos)").pack(side="left", padx=(0, 4))
        data_logger_count_entry = ttk.Entry(data_logger_timing, textvariable=self.data_logger_34970a_count_var, width=8)
        data_logger_count_entry.pack(side="left", padx=(0, 8))
        data_logger_stop_button = ttk.Button(data_logger_timing, text="Stop", command=self.stop_current_operation)
        data_logger_stop_button.pack(side="left", padx=(8, 0))
        ttk.Label(data_logger, text="Vorher einmal IDN testen, damit die funktionierenden COM-Settings gecacht werden.").grid(row=3, column=0, sticky="w", padx=8, pady=(0, 8))

        spectrum = ttk.LabelFrame(measurement_area, text="Spektrumanalysator")
        spectrum.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        spectrum_controls = ttk.Frame(spectrum)
        spectrum_controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        spectrum_trace_button = ttk.Button(spectrum_controls, text="Trace exportieren", command=self.capture_spectrum_trace)
        spectrum_trace_button.pack(side="left", padx=(0, 8))
        spectrum_screenshot_button = ttk.Button(spectrum_controls, text="Screenshot", command=self.capture_screenshot)
        spectrum_screenshot_button.pack(side="left", padx=(0, 8))

        generator = ttk.LabelFrame(measurement_area, text="Signalgenerator")
        generator.grid(row=6, column=0, sticky="ew", pady=(12, 0))
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
        power_supply.grid(row=7, column=0, sticky="ew", pady=(12, 0))
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

        ttk.Label(sequence, text="Komplexe Mess- und Schaltabläufe werden im freien Editor erstellt.").grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
        custom_sequence_button = ttk.Button(sequence, text="Freier Ablauf-Editor", command=self.open_custom_sequence_window)
        custom_sequence_button.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))

        timed_switch = ttk.LabelFrame(controls_frame, text="Getimtes Schalten")
        timed_switch.grid(row=5, column=0, sticky="ew", padx=12, pady=6)
        timed_switch.grid_remove()
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
        self._data_logger_widgets = [data_logger_read_button, data_logger_measurement_combo, data_logger_channels_entry, data_logger_baudrate_entry, data_logger_serial_format_combo, data_logger_plan_button, data_logger_plan_entry, data_logger_interval_entry, data_logger_count_entry]
        self._data_logger_stop_widgets = [data_logger_stop_button]
        self._spectrum_widgets = [spectrum_trace_button]
        self._spectrum_screenshot_widgets = [spectrum_screenshot_button]
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
            "data_logger": data_logger,
            "spectrum": spectrum,
            "generator": generator,
            "power_supply": power_supply,
        }
        self._sequence_widgets = [
            custom_sequence_button,
        ]
        self._sequence_stop_widgets = []
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

    def read_data_logger_34970a(self) -> None:
        self._run_worker("34970A-Kanäle werden gemessen...", self._read_data_logger_34970a)

    def read_data_logger_34970a_plan(self) -> None:
        self._run_worker("34970A-Messplan wird gemessen...", self._read_data_logger_34970a_plan)

    def stop_current_operation(self) -> None:
        self.operation_stop_event.set()
        self.status_var.set("Stop angefordert...")
        self._append_log("Stop angefordert...")

    def read_scope_measurement(self) -> None:
        self._run_worker("Scope-Messwert wird gelesen...", self._read_scope_measurement)

    def capture_screenshot(self) -> None:
        self._run_worker("Screenshot wird erfasst...", self._capture_screenshot)

    def capture_waveform(self) -> None:
        self._run_worker("Waveform wird erfasst...", self._capture_waveform)

    def capture_spectrum_trace(self) -> None:
        self._run_worker("Spektrum-Trace wird exportiert...", self._capture_spectrum_trace)

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

    def open_custom_sequence_window(self) -> None:
        if self.custom_sequence_window is not None and self.custom_sequence_window.winfo_exists():
            self.custom_sequence_window.lift()
            return
        window = tk.Toplevel(self)
        self.custom_sequence_window = window
        window.protocol("WM_DELETE_WINDOW", self._close_custom_sequence_window)
        window.title("Freier Ablauf-Editor")
        window.geometry("1400x860")
        window.minsize(1250, 780)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        settings = ttk.LabelFrame(window, text="Durchlauf")
        settings.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        for column in (1, 3, 5, 7):
            settings.columnconfigure(column, weight=1)
        ttk.Label(settings, text="Wiederholungen").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(settings, textvariable=self.custom_sequence_repeat_var, width=8).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Label(settings, text="Pause [s]").grid(row=0, column=2, sticky="w", padx=8, pady=8)
        ttk.Entry(settings, textvariable=self.custom_sequence_pause_var, width=8).grid(row=0, column=3, sticky="ew", padx=8, pady=8)
        ttk.Label(settings, text="Variable").grid(row=0, column=4, sticky="w", padx=8, pady=8)
        ttk.Entry(settings, textvariable=self.custom_sequence_variable_name_var, width=12).grid(row=0, column=5, sticky="ew", padx=8, pady=8)
        unit_combo = ttk.Combobox(settings, textvariable=self.custom_sequence_variable_unit_var, values=("frequency", "voltage", "number"), state="readonly", width=10)
        unit_combo.grid(row=0, column=6, sticky="ew", padx=8, pady=8)
        unit_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_custom_sequence_variable_unit_defaults())
        ttk.Label(settings, text="Start").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Entry(settings, textvariable=self.custom_sequence_variable_start_var, width=12).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(settings, text="Schritt").grid(row=1, column=2, sticky="w", padx=8, pady=(0, 8))
        ttk.Entry(settings, textvariable=self.custom_sequence_variable_step_var, width=12).grid(row=1, column=3, sticky="ew", padx=8, pady=(0, 8))
        ttk.Checkbutton(settings, text="RF am Ende aus", variable=self.custom_sequence_end_rf_off_var).grid(row=1, column=4, sticky="w", padx=8, pady=(0, 8))
        ttk.Checkbutton(settings, text="Netzgerät am Ende aus", variable=self.custom_sequence_end_supply_off_var).grid(row=1, column=5, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        body = ttk.Frame(window)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        body.columnconfigure(0, weight=2, minsize=600)
        body.columnconfigure(1, weight=3, minsize=620)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        left_canvas = tk.Canvas(left, highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(left, orient="vertical", command=left_canvas.yview)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scrollbar.grid(row=0, column=1, sticky="ns")
        left_content = ttk.Frame(left_canvas)
        left_content.columnconfigure(0, weight=1)
        left_window = left_canvas.create_window((0, 0), window=left_content, anchor="nw")
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_content.bind("<Configure>", lambda event: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.bind("<Configure>", lambda event: left_canvas.itemconfigure(left_window, width=event.width))
        left.bind("<Enter>", lambda event: left_canvas.bind_all("<MouseWheel>", lambda wheel_event: self._scroll_controls_if_needed(left_canvas, wheel_event)))
        left.bind("<Leave>", lambda event: left_canvas.unbind_all("<MouseWheel>"))
        self._build_custom_sequence_device_panel(left_content)
        self._build_custom_sequence_step_panel(left_content)

        right = ttk.LabelFrame(body, text="Ablauf-Liste")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.custom_sequence_tree = ttk.Treeview(right, columns=("nr", "device", "action", "params"), show="headings", height=16)
        for column, text, width in (("nr", "Nr.", 50), ("device", "Gerät", 140), ("action", "Aktion", 190), ("params", "Parameter", 420)):
            self.custom_sequence_tree.heading(column, text=text)
            self.custom_sequence_tree.column(column, width=width, anchor="w")
        self.custom_sequence_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.custom_sequence_tree.bind("<Double-1>", self._edit_custom_sequence_step_from_event)
        tree_scrollbar = ttk.Scrollbar(right, orient="vertical", command=self.custom_sequence_tree.yview)
        tree_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.custom_sequence_tree.configure(yscrollcommand=tree_scrollbar.set)
        step_buttons = ttk.Frame(right)
        step_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(step_buttons, text="Hoch", command=lambda: self._move_custom_sequence_step(-1)).pack(side="left", padx=(0, 8))
        ttk.Button(step_buttons, text="Runter", command=lambda: self._move_custom_sequence_step(1)).pack(side="left", padx=(0, 8))
        ttk.Button(step_buttons, text="Entfernen", command=self._remove_custom_sequence_step).pack(side="left", padx=(0, 8))
        ttk.Button(step_buttons, text="Leeren", command=self._clear_custom_sequence_steps).pack(side="left", padx=(0, 8))
        ttk.Button(step_buttons, text="Bearbeiten", command=self._edit_selected_custom_sequence_step).pack(side="left", padx=(0, 8))

        footer = ttk.Frame(window)
        footer.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 12))
        footer.columnconfigure(1, weight=1)
        self.custom_sequence_example_var = tk.StringVar(value=CUSTOM_SEQUENCE_EXAMPLES[0][0])
        ttk.Label(footer, text="Beispiel").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
        example_combo = ttk.Combobox(footer, textvariable=self.custom_sequence_example_var, values=tuple(label for label, _key in CUSTOM_SEQUENCE_EXAMPLES), state="readonly", width=34)
        example_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 6))
        ttk.Button(footer, text="Laden", command=self.load_selected_custom_sequence_example).grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=(0, 6))
        ttk.Button(footer, text="Import", command=self.import_custom_sequence).grid(row=0, column=3, sticky="ew", padx=(0, 8), pady=(0, 6))
        ttk.Button(footer, text="Export", command=self.export_custom_sequence).grid(row=0, column=4, sticky="ew", padx=(0, 8), pady=(0, 6))
        ttk.Button(footer, text="Vorschau", command=self.preview_custom_sequence).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(footer, text="Ablauf starten", command=self.start_custom_sequence).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(footer, text="Stop", command=self.stop_sequence).grid(row=1, column=2, sticky="ew", padx=(0, 8))
        ttk.Button(footer, text="Schließen", command=self._close_custom_sequence_window).grid(row=1, column=4, sticky="ew")
        self._refresh_custom_sequence_device_tree()
        self._refresh_custom_sequence_tree()

    def _close_custom_sequence_window(self) -> None:
        if self.custom_sequence_window is not None and self.custom_sequence_window.winfo_exists():
            self.custom_sequence_window.destroy()
        self.custom_sequence_window = None
        self.custom_sequence_tree = None
        self.custom_sequence_device_tree = None
        self.custom_sequence_device_select_combo = None
        self.custom_sequence_serial_port_combo = None
        self.custom_sequence_action_var = None
        self.custom_sequence_example_var = None
        self.custom_sequence_param_labels = {}
        self.custom_sequence_param_widgets = {}
        self.custom_sequence_step_button = None
        self.custom_sequence_edit_index = None

    def _build_custom_sequence_device_panel(self, parent: ttk.Frame) -> None:
        devices = ttk.LabelFrame(parent, text="Geräte")
        devices.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        devices.columnconfigure(1, weight=1)
        self.custom_sequence_device_select_var = tk.StringVar(value="")
        self.custom_sequence_device_name_var = tk.StringVar(value="Signalgenerator1")
        self.custom_sequence_device_address_var = tk.StringVar(value=self.address_var.get().strip())
        self.custom_sequence_device_role_var = tk.StringVar(value="Signalgenerator")
        ttk.Label(devices, text="Gefundenes Gerät").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.custom_sequence_device_select_combo = ttk.Combobox(devices, textvariable=self.custom_sequence_device_select_var, state="readonly", width=52)
        self.custom_sequence_device_select_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        self.custom_sequence_device_select_combo.bind("<<ComboboxSelected>>", self._apply_selected_resource_as_custom_sequence_device)
        ttk.Button(devices, text="übernehmen", command=self._apply_selected_resource_as_custom_sequence_device).grid(row=0, column=2, sticky="ew", padx=8, pady=8)
        ttk.Label(devices, text="Gerätetyp").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        role_combo = ttk.Combobox(devices, textvariable=self.custom_sequence_device_role_var, values=SEQUENCE_DEVICE_ROLES, state="readonly", width=24)
        role_combo.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))
        role_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_custom_sequence_device_role())
        ttk.Label(devices, text="Name").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Entry(devices, textvariable=self.custom_sequence_device_name_var, width=14).grid(row=2, column=1, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(devices, text="Adresse").grid(row=3, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Entry(devices, textvariable=self.custom_sequence_device_address_var).grid(row=3, column=1, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(devices, text="aktuelle Adresse", command=lambda: self.custom_sequence_device_address_var.set(self.address_var.get().strip()) if self.custom_sequence_device_address_var else None).grid(row=3, column=2, sticky="ew", padx=8, pady=(0, 8))
        self.custom_sequence_serial_port_var = tk.StringVar(value="")
        ttk.Label(devices, text="COM-Port").grid(row=4, column=0, sticky="w", padx=8, pady=(0, 8))
        self.custom_sequence_serial_port_combo = ttk.Combobox(devices, textvariable=self.custom_sequence_serial_port_var, state="readonly", width=42)
        self.custom_sequence_serial_port_combo.grid(row=4, column=1, sticky="ew", padx=8, pady=(0, 8))
        self.custom_sequence_serial_port_combo.bind("<<ComboboxSelected>>", self._apply_selected_serial_port_as_custom_sequence_device)
        serial_buttons = ttk.Frame(devices)
        serial_buttons.grid(row=4, column=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(serial_buttons, text="suchen", command=self._refresh_custom_sequence_serial_ports).pack(side="left", fill="x", expand=True)
        ttk.Button(serial_buttons, text="übernehmen", command=self._apply_selected_serial_port_as_custom_sequence_device).pack(side="left", fill="x", expand=True, padx=(6, 0))
        ttk.Button(devices, text="Gerät hinzufügen", command=self._add_custom_sequence_device).grid(row=5, column=1, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(devices, text="Gerät entfernen", command=self._remove_custom_sequence_device).grid(row=5, column=2, sticky="ew", padx=8, pady=(0, 8))
        self.custom_sequence_device_tree = ttk.Treeview(devices, columns=("name", "address"), show="headings", height=4)
        self.custom_sequence_device_tree.heading("name", text="Name")
        self.custom_sequence_device_tree.heading("address", text="Adresse")
        self.custom_sequence_device_tree.column("name", width=110)
        self.custom_sequence_device_tree.column("address", width=260)
        self.custom_sequence_device_tree.grid(row=6, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8))
        self._refresh_custom_sequence_resource_combo()
        self._refresh_custom_sequence_serial_ports()

    def _build_custom_sequence_step_panel(self, parent: ttk.Frame) -> None:
        steps = ttk.LabelFrame(parent, text="Schritt hinzufügen")
        steps.grid(row=1, column=0, sticky="nsew")
        steps.columnconfigure(1, weight=1)
        action_values = tuple(label for label, _action, _params in CUSTOM_SEQUENCE_ACTIONS)
        self.custom_sequence_action_var = tk.StringVar(value=action_values[0])
        ttk.Label(steps, text="Aktion").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        action_combo = ttk.Combobox(steps, textvariable=self.custom_sequence_action_var, values=action_values, state="readonly", width=52)
        action_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        action_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_custom_sequence_param_defaults())
        self.custom_sequence_param_vars = {
            "device": tk.StringVar(value="Signalgenerator1"),
            "value1": tk.StringVar(value="${frequency}"),
            "value2": tk.StringVar(value="-30 dBm"),
            "value3": tk.StringVar(value="0"),
            "value4": tk.StringVar(value="1"),
        }
        for row, (label, key) in enumerate((("Gerät", "device"), ("Wert 1", "value1"), ("Wert 2", "value2"), ("Wert 3", "value3"), ("Wert 4", "value4")), start=1):
            label_widget = ttk.Label(steps, text=label)
            label_widget.grid(row=row, column=0, sticky="w", padx=8, pady=(0, 8))
            self.custom_sequence_param_labels[key] = label_widget
            entry = ttk.Entry(steps, textvariable=self.custom_sequence_param_vars[key], width=52)
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=(0, 8))
            self.custom_sequence_param_widgets[key] = entry
        ttk.Label(steps, text="Variablen werden mit ${name} genutzt, z. B. ${frequency}.", wraplength=500).grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        self.custom_sequence_step_button = ttk.Button(steps, text="Schritt hinzufügen", command=self._add_custom_sequence_step)
        self.custom_sequence_step_button.grid(row=7, column=1, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(steps, text="Bearbeiten abbrechen", command=self._cancel_custom_sequence_step_edit).grid(row=8, column=1, sticky="ew", padx=8, pady=(0, 8))
        self._refresh_custom_sequence_param_defaults()

    def _refresh_custom_sequence_param_defaults(self) -> None:
        if not self.custom_sequence_action_var or not self.custom_sequence_param_vars:
            return
        action = self._selected_custom_sequence_action()[1]
        defaults = {
            "generator_set_frequency": (self._default_sequence_device_name("Signalgenerator"), "${frequency}", "-30 dBm", self.generator_max_power_var.get(), "ON"),
            "generator_set_power": (self._default_sequence_device_name("Signalgenerator"), self.generator_power_var.get(), self.generator_max_power_var.get(), "ON", "ON"),
            "generator_rf": (self._default_sequence_device_name("Signalgenerator"), "OFF", "", "", ""),
            "power_supply_set": (self._default_sequence_device_name("Netzgerät"), "${voltage}", self.power_supply_current_var.get(), str(self._safe_power_supply_channel_setting()), "ON"),
            "power_supply_output": (self._default_sequence_device_name("Netzgerät"), "OFF", str(self._safe_power_supply_channel_setting()), "", ""),
            "power_supply_master_output": (self._default_sequence_device_name("Netzgerät"), "OFF", str(self._safe_power_supply_channel_setting()), "", ""),
            "dmm_read": (self._default_sequence_device_name("Multimeter"), "", "", "", ""),
            "scope_measure": (self._default_sequence_device_name("Oszilloskop"), self.measurement_var.get(), str(self.channel_var.get()), "", ""),
            "capture_waveform": (self._default_sequence_device_name("Oszilloskop"), "1", self.point_mode_var.get(), "", ""),
            "capture_screenshot": (self._default_sequence_device_name("Oszilloskop"), "", "", "", ""),
            "serial_log": (self._default_sequence_device_name("Seriell"), "10", "115200", "8N1", ""),
            "parallel_phase": ("", "10", "1", "Multimeter1:dmm; Oszilloskop1:scope:Vpp:1; Seriell1:serial:115200:8N1", ""),
            "picoscope_analog": (self._default_sequence_device_name("PicoScope"), "A,B", "5V", "10000", "1"),
            "picoscope_digital": (self._default_sequence_device_name("PicoScope"), "D0-D7", "1500", "10000", "1"),
            "data_logger_34970a_read": (self._default_sequence_device_name("Datenlogger"), "TEMP", "1-20", "19200", "8N1"),
            "data_logger_34970a_plan": (self._default_sequence_device_name("Datenlogger"), "1-20:TEMP; 21-22:CURR_DC", "19200", "8N1", ""),
            "saleae_capture": (self._default_sequence_device_name("Saleae"), "D0-D7", "5", "10000000", "3.3"),
            "saleae_uart": (self._default_sequence_device_name("Saleae"), "0", "115200", "5", "10000000"),
            "saleae_i2c": (self._default_sequence_device_name("Saleae"), "0", "1", "5", "10000000"),
            "saleae_spi": (self._default_sequence_device_name("Saleae"), "0", "1", "2", "5"),
            "saleae_can": (self._default_sequence_device_name("Saleae"), "0", "500000", "5", "10000000"),
            "wait": ("", "0.5", "", "", ""),
        }.get(action, ("", "", "", "", ""))
        for key, value in zip(("device", "value1", "value2", "value3", "value4"), defaults):
            self.custom_sequence_param_vars[key].set(value)
        self._refresh_custom_sequence_param_labels(action)
        self._refresh_custom_sequence_param_widgets(action)

    def _refresh_custom_sequence_param_labels(self, action: str) -> None:
        labels = self._custom_sequence_param_labels(action)
        for key, fallback in (("device", "Gerät"), ("value1", "Wert 1"), ("value2", "Wert 2"), ("value3", "Wert 3"), ("value4", "Wert 4")):
            label = self.custom_sequence_param_labels.get(key)
            if label is not None:
                label.configure(text=labels.get(key, fallback))

    def _custom_sequence_param_labels(self, action: str) -> dict[str, str]:
        return {
            "generator_set_frequency": {"device": "Signalgenerator", "value1": "Frequenz", "value2": "Pegel", "value3": "Max. Pegel [dBm]", "value4": "RF"},
            "generator_set_power": {"device": "Signalgenerator", "value1": "Pegel", "value2": "Max. Pegel [dBm]", "value3": "RF", "value4": "RF vor Änderung aus"},
            "generator_rf": {"device": "Signalgenerator", "value1": "RF"},
            "power_supply_set": {"device": "Netzgerät", "value1": "Spannung", "value2": "Stromlimit", "value3": "Kanal", "value4": "Ausgang"},
            "power_supply_output": {"device": "Netzgerät", "value1": "Ausgang", "value2": "Kanal"},
            "power_supply_master_output": {"device": "Netzgerät", "value1": "Master-Ausgang", "value2": "Referenzkanal"},
            "dmm_read": {"device": "Multimeter"},
            "scope_measure": {"device": "Oszilloskop", "value1": "Messwert", "value2": "Kanal"},
            "capture_waveform": {"device": "Oszilloskop/Spektrum", "value1": "Kanäle", "value2": "Punktmodus"},
            "capture_screenshot": {"device": "Gerät"},
            "serial_log": {"device": "Serielles Gerät", "value1": "Dauer [s]", "value2": "Baudrate", "value3": "Format"},
            "parallel_phase": {"device": "", "value1": "Dauer [s]", "value2": "Intervall [s]", "value3": "Aufgaben"},
            "picoscope_analog": {"device": "PicoScope", "value1": "Kanäle", "value2": "Bereich", "value3": "Samples", "value4": "Intervall [us]"},
            "picoscope_digital": {"device": "PicoScope", "value1": "Kanäle", "value2": "Logikpegel [mV]", "value3": "Samples", "value4": "Intervall [us]"},
            "data_logger_34970a_read": {"device": "34970A", "value1": "Messart", "value2": "Kanäle", "value3": "Baudrate", "value4": "Format"},
            "data_logger_34970a_plan": {"device": "34970A", "value1": "Messplan", "value2": "Baudrate", "value3": "Format", "value4": ""},
            "saleae_capture": {"device": "Saleae", "value1": "Kanäle", "value2": "Dauer [s]", "value3": "Sample-Rate", "value4": "Schwelle [V]"},
            "saleae_uart": {"device": "Saleae", "value1": "Kanal", "value2": "Baudrate", "value3": "Dauer [s]", "value4": "Sample-Rate"},
            "saleae_i2c": {"device": "Saleae", "value1": "SDA", "value2": "SCL", "value3": "Dauer [s]", "value4": "Sample-Rate"},
            "saleae_spi": {"device": "Saleae", "value1": "MOSI", "value2": "MISO", "value3": "Clock", "value4": "Dauer [s]"},
            "saleae_can": {"device": "Saleae", "value1": "Kanal", "value2": "Bitrate", "value3": "Dauer [s]", "value4": "Sample-Rate"},
            "wait": {"device": "", "value1": "Sekunden"},
        }.get(action, {})

    def _refresh_custom_sequence_param_widgets(self, action: str) -> None:
        combo_values = self._custom_sequence_param_combo_values(action)
        for key in ("value1", "value2", "value3", "value4"):
            current = self.custom_sequence_param_widgets.get(key)
            if current is None:
                continue
            grid_info = current.grid_info()
            current.destroy()
            values = combo_values.get(key)
            if values:
                widget = ttk.Combobox(current.master, textvariable=self.custom_sequence_param_vars[key], values=values, state="readonly", width=52)
            else:
                widget = ttk.Entry(current.master, textvariable=self.custom_sequence_param_vars[key], width=52)
            widget.grid(**grid_info)
            self.custom_sequence_param_widgets[key] = widget

    def _custom_sequence_param_combo_values(self, action: str) -> dict[str, tuple[str, ...]]:
        if action == "generator_set_frequency":
            return {"value4": ON_OFF_VALUES}
        if action == "generator_set_power":
            return {"value3": ON_OFF_VALUES, "value4": ON_OFF_VALUES}
        if action == "generator_rf":
            return {"value1": ON_OFF_VALUES}
        if action == "power_supply_set":
            return {"value3": CHANNEL_VALUES, "value4": ON_OFF_VALUES}
        if action == "power_supply_output":
            return {"value1": ON_OFF_VALUES, "value2": CHANNEL_VALUES}
        if action == "power_supply_master_output":
            return {"value1": ON_OFF_VALUES, "value2": CHANNEL_VALUES}
        if action == "scope_measure":
            return {"value1": SCOPE_MEASUREMENTS, "value2": CHANNEL_VALUES}
        if action == "capture_waveform":
            return {"value2": POINT_MODE_VALUES}
        if action == "serial_log":
            return {"value3": SERIAL_FORMAT_VALUES}
        if action == "picoscope_analog":
            return {"value2": PICOSCOPE_RANGE_VALUES}
        if action == "data_logger_34970a_read":
            return {"value1": DATA_LOGGER_34970A_MEASUREMENTS, "value4": SERIAL_FORMAT_VALUES}
        if action == "data_logger_34970a_plan":
            return {"value3": SERIAL_FORMAT_VALUES}
        return {}

    def _apply_custom_sequence_variable_unit_defaults(self) -> None:
        unit = self.custom_sequence_variable_unit_var.get().strip()
        defaults = {
            "frequency": ("frequency", "100 MHz", "1 MHz"),
            "voltage": ("voltage", "0 V", "1 V"),
            "number": ("value", "0", "1"),
        }
        name, start, step = defaults.get(unit, defaults["number"])
        self.custom_sequence_variable_name_var.set(name)
        self.custom_sequence_variable_start_var.set(start)
        self.custom_sequence_variable_step_var.set(step)

    def _selected_custom_sequence_action(self) -> tuple[str, str, tuple[str, ...]]:
        selected = self.custom_sequence_action_var.get() if self.custom_sequence_action_var is not None else ""
        for action in CUSTOM_SEQUENCE_ACTIONS:
            if action[0] == selected:
                return action
        return CUSTOM_SEQUENCE_ACTIONS[0]

    def _custom_sequence_action_label(self, action_key: str) -> str:
        for label, action, _params in CUSTOM_SEQUENCE_ACTIONS:
            if action == action_key:
                return label
        return CUSTOM_SEQUENCE_ACTIONS[0][0]

    def _custom_sequence_action_params(self, action_key: str) -> tuple[str, ...]:
        for _label, action, params in CUSTOM_SEQUENCE_ACTIONS:
            if action == action_key:
                return params
        return CUSTOM_SEQUENCE_ACTIONS[0][2]

    def _add_custom_sequence_device(self) -> None:
        if self.custom_sequence_device_name_var is None or self.custom_sequence_device_address_var is None:
            return
        name = self.custom_sequence_device_name_var.get().strip()
        address = self.custom_sequence_device_address_var.get().strip()
        if not name or not address:
            messagebox.showerror("Freier Ablauf", "Gerätename und Adresse dürfen nicht leer sein.")
            return
        self.custom_sequence_devices[name] = address
        self._refresh_custom_sequence_device_tree()

    def _refresh_custom_sequence_resource_combo(self) -> None:
        if self.custom_sequence_device_select_combo is None or self.custom_sequence_device_select_var is None:
            return
        labels: list[str] = []
        self.custom_sequence_device_select_map = {}
        resource_addresses = self._resource_display_addresses(self.last_found_resources)
        numbering = self._resource_numbering_for_addresses(resource_addresses)
        for address in resource_addresses:
            label = self._resource_display_label(address, numbering)
            if label not in self.custom_sequence_device_select_map:
                labels.append(label)
            self.custom_sequence_device_select_map[label] = address
        try:
            if not self.custom_sequence_device_select_combo.winfo_exists():
                self.custom_sequence_device_select_combo = None
                return
            self.custom_sequence_device_select_combo.configure(values=labels)
        except tk.TclError:
            self.custom_sequence_device_select_combo = None
            return
        if labels and not self.custom_sequence_device_select_var.get():
            self.custom_sequence_device_select_var.set(labels[0])

    def _apply_selected_resource_as_custom_sequence_device(self, event: tk.Event | None = None) -> None:
        if self.custom_sequence_device_select_var is None or self.custom_sequence_device_address_var is None or self.custom_sequence_device_name_var is None:
            return
        label = self.custom_sequence_device_select_var.get().strip()
        address = self.custom_sequence_device_select_map.get(label, label)
        if not address:
            return
        self.custom_sequence_device_address_var.set(address)
        saved = self._saved_device_for_address(address)
        role = self._sequence_role_from_saved_device(saved) if isinstance(saved, dict) else self._sequence_role_from_profile(self.current_profile)
        if self.custom_sequence_device_role_var is not None:
            self.custom_sequence_device_role_var.set(role)
        self.custom_sequence_device_name_var.set(self._next_sequence_device_name(role))

    def _refresh_custom_sequence_serial_ports(self) -> None:
        if self.custom_sequence_serial_port_combo is None or self.custom_sequence_serial_port_var is None:
            return
        labels: list[str] = []
        self.custom_sequence_serial_port_map = {}
        for port in list_direct_serial_ports():
            label = self._serial_port_display_label(port)
            labels.append(label)
            self.custom_sequence_serial_port_map[label] = port.device
        try:
            if not self.custom_sequence_serial_port_combo.winfo_exists():
                self.custom_sequence_serial_port_combo = None
                return
            self.custom_sequence_serial_port_combo.configure(values=labels)
        except tk.TclError:
            self.custom_sequence_serial_port_combo = None
            return
        if labels:
            self.custom_sequence_serial_port_var.set(labels[0])
            self.status_var.set(f"COM-Ports gefunden: {len(labels)}")
        else:
            self.custom_sequence_serial_port_var.set("")
            self.status_var.set("Keine COM-Ports gefunden.")

    def _serial_port_display_label(self, port) -> str:
        description = str(getattr(port, "description", "")).strip()
        return f"{port.device} - {description}" if description else str(port.device)

    def _apply_selected_serial_port_as_custom_sequence_device(self, event: tk.Event | None = None) -> None:
        if self.custom_sequence_serial_port_var is None or self.custom_sequence_device_address_var is None or self.custom_sequence_device_name_var is None:
            return
        label = self.custom_sequence_serial_port_var.get().strip()
        port = self.custom_sequence_serial_port_map.get(label, label.split(" - ", 1)[0].strip())
        if not port:
            return
        self.custom_sequence_device_address_var.set(port)
        if self.custom_sequence_device_role_var is not None:
            self.custom_sequence_device_role_var.set("Seriell")
        self.custom_sequence_device_name_var.set(self._next_sequence_device_name("Seriell"))

    def _sequence_role_from_saved_device(self, saved: dict) -> str:
        profile = self._profile_from_settings(saved)
        return self._sequence_role_from_profile(profile)

    def _sequence_role_from_profile(self, profile: DeviceProfile) -> str:
        device_type = profile.device_type.lower()
        if profile.supports_signal_generator:
            return "Signalgenerator"
        if profile.supports_power_supply:
            return "Netzgerät"
        if profile.supports_dmm_read:
            return "Multimeter"
        if profile.supports_scope_measurements:
            return "Oszilloskop"
        if "spektrum" in device_type:
            return "Spektrumanalysator"
        if profile.supports_sparameters or "netzwerk" in device_type:
            return "Netzwerkanalysator"
        return profile.device_type if profile.device_type not in {"Nicht erkannt", "Unbekannt"} else "Gerät"

    def _apply_custom_sequence_device_role(self) -> None:
        if self.custom_sequence_device_role_var is None or self.custom_sequence_device_name_var is None or self.custom_sequence_device_address_var is None:
            return
        role = self.custom_sequence_device_role_var.get().strip()
        self.custom_sequence_device_name_var.set(self._next_sequence_device_name(role))
        self.custom_sequence_device_address_var.set(self._example_address(role, self.address_var.get().strip()))

    def _default_sequence_device_name(self, role: str) -> str:
        matches = [name for name in self.custom_sequence_devices if self._sequence_device_name_matches_role(name, role)]
        return matches[0] if matches else self._next_sequence_device_name(role)

    def _next_sequence_device_name(self, role: str) -> str:
        role = self._sequence_device_role_name(role)
        index = 1
        while f"{role}{index}" in self.custom_sequence_devices:
            index += 1
        return f"{role}{index}"

    def _sequence_device_name_matches_role(self, name: str, role: str) -> bool:
        return name.lower().startswith(self._sequence_device_role_name(role).lower())

    def _sequence_device_role_name(self, role: str) -> str:
        normalized = role.strip().lower()
        if normalized in {"dmm", "multimeter"}:
            return "Multimeter"
        if normalized in {"supply", "netzteil", "netzgerät"}:
            return "Netzgerät"
        if normalized in {"scope", "oszilloskop"}:
            return "Oszilloskop"
        if normalized in {"generator", "signalgenerator"}:
            return "Signalgenerator"
        if normalized in {"spectrum", "spektrum", "spektrumanalysator"}:
            return "Spektrumanalysator"
        if normalized in {"serial", "seriell", "com", "comport", "com-port"}:
            return "Seriell"
        if normalized in {"pico", "picoscope"}:
            return "PicoScope"
        if normalized in {"saleae", "logic", "logic2"}:
            return "Saleae"
        if normalized in {"datenlogger", "logger", "datalogger", "data logger", "34970a"}:
            return "Datenlogger"
        return role.strip() or "Gerät"

    def _remove_custom_sequence_device(self) -> None:
        if self.custom_sequence_device_tree is None:
            return
        selected = self.custom_sequence_device_tree.selection()
        if not selected:
            return
        name = self.custom_sequence_device_tree.item(selected[0], "values")[0]
        self.custom_sequence_devices.pop(str(name), None)
        self._refresh_custom_sequence_device_tree()

    def _refresh_custom_sequence_device_tree(self) -> None:
        if self.custom_sequence_device_tree is None:
            return
        self.custom_sequence_device_tree.delete(*self.custom_sequence_device_tree.get_children())
        for name, address in self.custom_sequence_devices.items():
            self.custom_sequence_device_tree.insert("", "end", values=(name, address))

    def _add_custom_sequence_step(self) -> None:
        try:
            label, action, param_names = self._selected_custom_sequence_action()
            raw_values = [self.custom_sequence_param_vars[key].get().strip() for key in ("device", "value1", "value2", "value3", "value4")]
            values_by_name = dict(zip(param_names, raw_values))
            device = values_by_name.pop("device", "")
            params = {name: value for name, value in values_by_name.items() if value != ""}
            if action not in {"wait", "parallel_phase"} and not device:
                raise ValueError("Bitte Gerätename für den Schritt eintragen.")
            step = SequenceStep(device=device, action=action, params=params)
            if self.custom_sequence_edit_index is None:
                self.custom_sequence_steps.append(step)
                status = f"Schritt hinzugefügt: {label}"
            else:
                self.custom_sequence_steps[self.custom_sequence_edit_index] = step
                status = f"Schritt aktualisiert: {label}"
                self.custom_sequence_edit_index = None
                if self.custom_sequence_step_button is not None:
                    self.custom_sequence_step_button.configure(text="Schritt hinzufügen")
        except ValueError as exc:
            messagebox.showerror("Freier Ablauf", str(exc))
            return
        self._refresh_custom_sequence_tree()
        self.status_var.set(status)

    def _cancel_custom_sequence_step_edit(self) -> None:
        self.custom_sequence_edit_index = None
        if self.custom_sequence_step_button is not None:
            self.custom_sequence_step_button.configure(text="Schritt hinzufügen")
        self._refresh_custom_sequence_param_defaults()
        self.status_var.set("Schritt-Bearbeitung abgebrochen.")

    def _refresh_custom_sequence_tree(self) -> None:
        if self.custom_sequence_tree is None:
            return
        self.custom_sequence_tree.delete(*self.custom_sequence_tree.get_children())
        for index, step in enumerate(self.custom_sequence_steps, start=1):
            self.custom_sequence_tree.insert("", "end", iid=str(index - 1), values=(index, step.device, step.action, _format_step_params(step.params)))

    def _selected_custom_sequence_step_index(self) -> int | None:
        if self.custom_sequence_tree is None:
            return None
        selected = self.custom_sequence_tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def _edit_custom_sequence_step_from_event(self, event: tk.Event) -> None:
        if self.custom_sequence_tree is None:
            return
        row_id = self.custom_sequence_tree.identify_row(event.y)
        if row_id:
            self.custom_sequence_tree.selection_set(row_id)
            self._edit_selected_custom_sequence_step()

    def _edit_selected_custom_sequence_step(self) -> None:
        index = self._selected_custom_sequence_step_index()
        if index is None or index < 0 or index >= len(self.custom_sequence_steps):
            return
        step = self.custom_sequence_steps[index]
        self.custom_sequence_edit_index = index
        if self.custom_sequence_action_var is not None:
            self.custom_sequence_action_var.set(self._custom_sequence_action_label(step.action))
        self._refresh_custom_sequence_param_labels(step.action)
        self._refresh_custom_sequence_param_widgets(step.action)
        param_names = self._custom_sequence_action_params(step.action)
        values = {"device": step.device, **{name: str(value) for name, value in step.params.items()}}
        for key, param_name in zip(("device", "value1", "value2", "value3", "value4"), param_names):
            self.custom_sequence_param_vars[key].set(values.get(param_name, ""))
        for key in ("value1", "value2", "value3", "value4"):
            if key not in dict(zip(("device", "value1", "value2", "value3", "value4"), param_names)):
                self.custom_sequence_param_vars[key].set("")
        if self.custom_sequence_step_button is not None:
            self.custom_sequence_step_button.configure(text="Schritt aktualisieren")
        self.status_var.set(f"Schritt {index + 1} wird bearbeitet.")

    def _move_custom_sequence_step(self, direction: int) -> None:
        index = self._selected_custom_sequence_step_index()
        if index is None:
            return
        new_index = index + direction
        if new_index < 0 or new_index >= len(self.custom_sequence_steps):
            return
        self.custom_sequence_steps[index], self.custom_sequence_steps[new_index] = self.custom_sequence_steps[new_index], self.custom_sequence_steps[index]
        self._refresh_custom_sequence_tree()
        if self.custom_sequence_tree is not None:
            self.custom_sequence_tree.selection_set(str(new_index))

    def _remove_custom_sequence_step(self) -> None:
        index = self._selected_custom_sequence_step_index()
        if index is None:
            return
        del self.custom_sequence_steps[index]
        self._refresh_custom_sequence_tree()

    def _clear_custom_sequence_steps(self) -> None:
        self.custom_sequence_steps.clear()
        self._cancel_custom_sequence_step_edit()
        self._refresh_custom_sequence_tree()

    def preview_custom_sequence(self) -> None:
        try:
            config = self._custom_sequence_config()
        except ValueError as exc:
            messagebox.showerror("Freier Ablauf", str(exc))
            return
        wait_s = self._custom_sequence_wait_seconds(config)
        duration = wait_s * config.repeat + config.pause_s * max(0, config.repeat - 1)
        variable_text = ", ".join(f"{variable.name}: {variable.start} + {variable.step}/Durchlauf" for variable in config.variables) or "keine"
        messagebox.showinfo(
            "Freier Ablauf",
            f"Geräte: {len(config.devices)}\nSchritte pro Durchlauf: {len(config.steps)}\nWiederholungen: {config.repeat}\nPause zwischen Durchläufen: {config.pause_s:.3f} s\nExplizite Wartezeit pro Durchlauf: {wait_s:.3f} s\nGeschätzte Mindestdauer: {duration:.1f} s\nVariablen: {variable_text}",
        )

    def _custom_sequence_wait_seconds(self, config: CustomSequenceConfig) -> float:
        total = 0.0
        for step in config.steps:
            try:
                if step.action == "wait":
                    total += float(str(step.params.get("seconds", "0")).replace(",", "."))
                elif step.action == "serial_log":
                    total += float(str(step.params.get("duration_s", "0")).replace(",", "."))
            except ValueError:
                pass
        return total

    def load_selected_custom_sequence_example(self) -> None:
        selected = self.custom_sequence_example_var.get() if self.custom_sequence_example_var is not None else ""
        for label, key in CUSTOM_SEQUENCE_EXAMPLES:
            if label == selected:
                self._load_custom_sequence_example(key)
                return

    def _load_custom_sequence_example(self, example: str) -> None:
        current_address = self.address_var.get().strip()
        generator_address = self._example_address("Signalgenerator", current_address)
        dmm_address = self._example_address("Multimeter", current_address)
        scope_address = self._example_address("Oszilloskop", current_address)
        spectrum_address = self._example_address("Spektrumanalysator", current_address)
        supply_address = self._example_address("Netzgerät", current_address)
        if example == "timed_dmm":
            self.custom_sequence_devices = {"Multimeter1": dmm_address}
            self.custom_sequence_steps = [SequenceStep("Multimeter1", "dmm_read")]
            self.custom_sequence_repeat_var.set(self.timed_count_var.get())
            self.custom_sequence_pause_var.set(self.timed_interval_var.get())
            self.custom_sequence_variable_name_var.set("")
            self.custom_sequence_variable_start_var.set("")
            self.custom_sequence_variable_step_var.set("")
            self.status_var.set("Beispiel geladen: getimtes Multimeter-Messen")
        elif example == "timed_scope":
            self.custom_sequence_devices = {"Oszilloskop1": scope_address}
            self.custom_sequence_steps = [SequenceStep("Oszilloskop1", "scope_measure", {"measurement": self.measurement_var.get(), "channel": str(self.channel_var.get())})]
            self.custom_sequence_repeat_var.set(self.timed_count_var.get())
            self.custom_sequence_pause_var.set(self.timed_interval_var.get())
            self.custom_sequence_variable_name_var.set("")
            self.custom_sequence_variable_start_var.set("")
            self.custom_sequence_variable_step_var.set("")
            self.status_var.set("Beispiel geladen: getimtes Oszilloskop-Messen")
        elif example == "rf_switch":
            self.custom_sequence_devices = {"Signalgenerator1": generator_address}
            self.custom_sequence_steps = [
                SequenceStep("Signalgenerator1", "generator_rf", {"enabled": "ON"}),
                SequenceStep("", "wait", {"seconds": self.switch_on_s_var.get()}),
                SequenceStep("Signalgenerator1", "generator_rf", {"enabled": "OFF"}),
                SequenceStep("", "wait", {"seconds": self.switch_off_s_var.get()}),
            ]
            self.custom_sequence_repeat_var.set(self.switch_repetitions_var.get())
            self.custom_sequence_pause_var.set("0")
            self.custom_sequence_variable_name_var.set("")
            self.custom_sequence_variable_start_var.set("")
            self.custom_sequence_variable_step_var.set("")
            self.custom_sequence_end_rf_off_var.set(True)
            self.status_var.set("Beispiel geladen: RF getimt schalten")
        elif example == "generator_dmm":
            self.custom_sequence_devices = {"Signalgenerator1": generator_address, "Multimeter1": dmm_address}
            self.custom_sequence_steps = [
                SequenceStep("Signalgenerator1", "generator_set_frequency", {"frequency": "${frequency}", "power": self.generator_power_var.get(), "max_power_dbm": self.generator_max_power_var.get(), "rf": "ON"}),
                SequenceStep("", "wait", {"seconds": "0.5"}),
                SequenceStep("Multimeter1", "dmm_read"),
            ]
            self._set_custom_sequence_frequency_defaults(repeat="10")
            self.custom_sequence_end_rf_off_var.set(True)
            self.status_var.set("Beispiel geladen: Signalgenerator + Multimeter")
        elif example == "generator_scope":
            self.custom_sequence_devices = {"Signalgenerator1": generator_address, "Oszilloskop1": scope_address}
            self.custom_sequence_steps = [
                SequenceStep("Signalgenerator1", "generator_set_frequency", {"frequency": "${frequency}", "power": self.generator_power_var.get(), "max_power_dbm": self.generator_max_power_var.get(), "rf": "ON"}),
                SequenceStep("", "wait", {"seconds": "0.5"}),
                SequenceStep("Oszilloskop1", "scope_measure", {"measurement": self.measurement_var.get(), "channel": str(self.channel_var.get())}),
            ]
            self._set_custom_sequence_frequency_defaults(repeat="10")
            self.custom_sequence_end_rf_off_var.set(True)
            self.status_var.set("Beispiel geladen: Signalgenerator + Oszilloskop")
        elif example == "supply_scope":
            self.custom_sequence_devices = {"Netzgerät1": supply_address, "Oszilloskop1": scope_address}
            self.custom_sequence_steps = [
                SequenceStep("Netzgerät1", "power_supply_set", {"voltage": "${voltage}", "current": self.power_supply_current_var.get(), "channel": str(self._safe_power_supply_channel_setting()), "output": "ON"}),
                SequenceStep("", "wait", {"seconds": "0.5"}),
                SequenceStep("Oszilloskop1", "scope_measure", {"measurement": self.measurement_var.get(), "channel": str(self.channel_var.get())}),
            ]
            self._set_custom_sequence_voltage_defaults(repeat="6")
            self.custom_sequence_end_supply_off_var.set(True)
            self.status_var.set("Beispiel geladen: Netzgerät + Oszilloskop")
        elif example == "generator_spectrum":
            self.custom_sequence_devices = {"Signalgenerator1": generator_address, "Spektrumanalysator1": spectrum_address}
            self.custom_sequence_steps = [
                SequenceStep("Signalgenerator1", "generator_set_frequency", {"frequency": "${frequency}", "power": self.generator_power_var.get(), "max_power_dbm": self.generator_max_power_var.get(), "rf": "ON"}),
                SequenceStep("", "wait", {"seconds": "0.5"}),
                SequenceStep("Spektrumanalysator1", "capture_waveform", {"channels": "", "point_mode": "RAW"}),
            ]
            self._set_custom_sequence_frequency_defaults(repeat="10")
            self.custom_sequence_end_rf_off_var.set(True)
            self.status_var.set("Beispiel geladen: Signalgenerator + Spektrumanalysator")
        elif example == "supply_dmm":
            self.custom_sequence_devices = {"Netzgerät1": supply_address, "Multimeter1": dmm_address}
            self.custom_sequence_steps = [
                SequenceStep("Netzgerät1", "power_supply_set", {"voltage": "${voltage}", "current": self.power_supply_current_var.get(), "channel": str(self._safe_power_supply_channel_setting()), "output": "ON"}),
                SequenceStep("", "wait", {"seconds": "0.5"}),
                SequenceStep("Multimeter1", "dmm_read"),
            ]
            self._set_custom_sequence_voltage_defaults(repeat="6")
            self.custom_sequence_end_supply_off_var.set(True)
            self.status_var.set("Beispiel geladen: Netzgerät + Multimeter")
        elif example == "supply_switch":
            self.custom_sequence_devices = {"Netzgerät1": supply_address}
            self.custom_sequence_steps = [
                SequenceStep("Netzgerät1", "power_supply_output", {"enabled": "ON", "channel": str(self._safe_power_supply_channel_setting())}),
                SequenceStep("", "wait", {"seconds": self.switch_on_s_var.get()}),
                SequenceStep("Netzgerät1", "power_supply_output", {"enabled": "OFF", "channel": str(self._safe_power_supply_channel_setting())}),
                SequenceStep("", "wait", {"seconds": self.switch_off_s_var.get()}),
            ]
            self.custom_sequence_repeat_var.set(self.switch_repetitions_var.get())
            self.custom_sequence_pause_var.set("0")
            self.custom_sequence_variable_name_var.set("")
            self.custom_sequence_variable_start_var.set("")
            self.custom_sequence_variable_step_var.set("")
            self.custom_sequence_end_supply_off_var.set(True)
            self.status_var.set("Beispiel geladen: Netzgerät getimt schalten")
        else:
            return
        self._refresh_custom_sequence_device_tree()
        self._refresh_custom_sequence_tree()

    def _example_address(self, role: str, fallback: str) -> str:
        if self._sequence_device_role_name(role) == "PicoScope":
            return "PICO2000A::AUTO"
        if self._sequence_device_role_name(role) == "Saleae":
            return "SALEAE::LOCAL"
        for address in self._known_device_addresses():
            saved = self._saved_device_for_address(address)
            if isinstance(saved, dict) and self._saved_device_matches_example_role(saved, role):
                return str(saved.get("address", address)).strip() or address
        return fallback

    def _saved_device_matches_example_role(self, saved: dict, role: str) -> bool:
        role = role.lower()
        device_type = str(saved.get("device_type", "")).lower()
        if role == "signalgenerator":
            return bool(saved.get("supports_signal_generator")) or "signalgenerator" in device_type or "generator" in device_type
        if role in {"dmm", "multimeter"}:
            return bool(saved.get("supports_dmm_read")) or "multimeter" in device_type or "dmm" in device_type
        if role in {"scope", "oszilloskop"}:
            return bool(saved.get("supports_scope_measurements")) or "oszilloskop" in device_type or "scope" in device_type
        if role in {"spektrum", "spektrumanalysator"}:
            return bool(saved.get("supports_waveform")) and ("spektrum" in device_type or "analysator" in device_type)
        if role in {"netzteil", "netzgerät"}:
            return bool(saved.get("supports_power_supply")) or "netzgerät" in device_type or "netzteil" in device_type
        return role in device_type

    def _set_custom_sequence_frequency_defaults(self, repeat: str) -> None:
        self.custom_sequence_repeat_var.set(repeat)
        self.custom_sequence_pause_var.set("0")
        self.custom_sequence_variable_unit_var.set("frequency")
        self.custom_sequence_variable_name_var.set("frequency")
        self.custom_sequence_variable_start_var.set(self.sequence_start_frequency_var.get())
        self.custom_sequence_variable_step_var.set(self.sequence_step_frequency_var.get())

    def _set_custom_sequence_voltage_defaults(self, repeat: str) -> None:
        self.custom_sequence_repeat_var.set(repeat)
        self.custom_sequence_pause_var.set("0")
        self.custom_sequence_variable_unit_var.set("voltage")
        self.custom_sequence_variable_name_var.set("voltage")
        self.custom_sequence_variable_start_var.set(self.sequence_start_voltage_var.get())
        self.custom_sequence_variable_step_var.set(self.sequence_step_voltage_var.get())

    def export_custom_sequence(self) -> None:
        try:
            data = self._custom_sequence_export_data()
        except ValueError as exc:
            messagebox.showerror("Ablauf exportieren", str(exc))
            return
        selected = filedialog.asksaveasfilename(
            title="Ablauf exportieren",
            defaultextension=".json",
            filetypes=[("Ablauf-Dateien", "*.json"), ("Alle Dateien", "*.*")],
            initialfile="ablauf.json",
        )
        if not selected:
            return
        selected_path = Path(selected)
        try:
            _write_sequence_data_file(selected_path, data)
        except RuntimeError as exc:
            messagebox.showerror("Ablauf exportieren", str(exc))
            return
        self.status_var.set(f"Ablauf exportiert: {selected}")
        self._append_log(f"Ablauf exportiert: {selected}")

    def import_custom_sequence(self) -> None:
        selected = filedialog.askopenfilename(
            title="Ablauf importieren",
            filetypes=[("Ablauf-Dateien", "*.json"), ("Alle Dateien", "*.*")],
        )
        if not selected:
            return
        try:
            data = _read_sequence_data_file(Path(selected))
            self._apply_custom_sequence_import_data(data)
        except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Ablauf importieren", str(exc))
            return
        self.status_var.set(f"Ablauf importiert: {selected}")
        self._append_log(f"Ablauf importiert: {selected}")

    def _custom_sequence_export_data(self) -> dict:
        config = self._custom_sequence_config()
        return {
            "version": CUSTOM_SEQUENCE_FILE_VERSION,
            "repeat": config.repeat,
            "pause_s": config.pause_s,
            "variables": [asdict(variable) for variable in config.variables],
            "devices": config.devices,
            "steps": [{"device": step.device, "action": step.action, "params": step.params} for step in config.steps],
            "end_rf_off": config.end_rf_off,
            "end_power_supply_off": config.end_power_supply_off,
            "power_supply_max_voltage": config.power_supply_max_voltage,
            "power_supply_max_current": config.power_supply_max_current,
        }

    def _apply_custom_sequence_import_data(self, data: object) -> None:
        if not isinstance(data, dict):
            raise ValueError("Ablauf-Datei muss ein JSON-Objekt enthalten.")
        devices = data.get("devices", {})
        steps = data.get("steps", [])
        variables = data.get("variables", [])
        if not isinstance(devices, dict) or not isinstance(steps, list):
            raise ValueError("Ablauf-Datei enthält ungültige Geräte oder Schritte.")
        self.custom_sequence_devices = {str(name): str(address) for name, address in devices.items()}
        imported_steps: list[SequenceStep] = []
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Ablauf-Datei enthält einen ungültigen Schritt.")
            imported_steps.append(self._step_from_settings(step))
        self.custom_sequence_steps = imported_steps
        self.custom_sequence_repeat_var.set(str(data.get("repeat", "1")))
        self.custom_sequence_pause_var.set(str(data.get("pause_s", "0")))
        if isinstance(variables, list) and variables and isinstance(variables[0], dict):
            variable = variables[0]
            self.custom_sequence_variable_name_var.set(str(variable.get("name", "")))
            self.custom_sequence_variable_unit_var.set(str(variable.get("unit", "number")))
            self.custom_sequence_variable_start_var.set(str(variable.get("start", "")))
            self.custom_sequence_variable_step_var.set(str(variable.get("step", "")))
        else:
            self.custom_sequence_variable_name_var.set("")
            self.custom_sequence_variable_start_var.set("")
            self.custom_sequence_variable_step_var.set("")
        self.custom_sequence_end_rf_off_var.set(parse_json_bool(data.get("end_rf_off"), True))
        self.custom_sequence_end_supply_off_var.set(parse_json_bool(data.get("end_power_supply_off"), False))
        self.power_supply_max_voltage_var.set(str(data.get("power_supply_max_voltage", self.power_supply_max_voltage_var.get())))
        self.power_supply_max_current_var.set(str(data.get("power_supply_max_current", self.power_supply_max_current_var.get())))
        self._refresh_custom_sequence_device_tree()
        self._refresh_custom_sequence_tree()

    def start_custom_sequence(self) -> None:
        if self.sequence_running:
            messagebox.showwarning("Freier Ablauf", "Es läuft bereits ein Ablauf.")
            return
        if self.timed_running or self.switch_running:
            messagebox.showwarning("Freier Ablauf", "Bitte zuerst laufende Abläufe stoppen.")
            return
        try:
            config = self._custom_sequence_config()
        except ValueError as exc:
            messagebox.showerror("Freier Ablauf", str(exc))
            return
        self.sequence_stop_event.clear()
        self.sequence_running = True
        self._set_sequence_running(True)
        self.status_var.set("Freier Ablauf läuft...")
        self._append_log("Freier Ablauf läuft...")
        self.logger.info("Freier Ablauf läuft...")
        thread = threading.Thread(target=self._worker_target, args=(lambda: self._run_custom_sequence(config),), daemon=True)
        thread.start()

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
        resources = list(dict.fromkeys([*list_resources(), *self._manual_device_resources()]))
        identification_results = self._identify_discovered_resources(resources)
        if resources:
            self._messages.put(("resources", "\n".join(resources)))
            result = "Gefundene Geräte:\n" + "\n".join(resources)
            if identification_results:
                result += "\n\nIDN-Prüfung:\n" + "\n".join(identification_results)
            return result
        return "Keine VISA-Geräte gefunden. Bekannte Adresse kann manuell eingetragen werden."

    def _identify_discovered_resources(self, resources: list[str]) -> list[str]:
        results: list[str] = []
        checked: set[str] = set()
        for address in resources:
            canonical_address = self._canonical_address(address)
            if canonical_address in checked:
                continue
            checked.add(canonical_address)
            port = self._serial_port_for_address(address)
            idn = ""
            serial_settings = None
            if port is None:
                try:
                    instrument_factory = create_sequence_instrument if address.strip().upper().startswith(("PICO::", "PICO2000A::", "SALEAE::")) else VisaInstrument
                    with instrument_factory(address=address, timeout_ms=1500) as instrument:
                        idn = instrument.info().idn.strip()
                except Exception as exc:
                    self.logger.info("IDN probe failed address=%s error=%s", address, exc)
                if idn:
                    profile = detect_profile(idn)
                    self._messages.put(("profile", (profile, address, idn, None)))
                    results.append(f"{address}: IDN erkannt - {idn}")
                else:
                    results.append(f"{address}: keine IDN-Antwort")
                continue

            if not address.strip().upper().startswith("COM"):
                try:
                    with VisaInstrument(address=address, timeout_ms=1500) as instrument:
                        idn = instrument.info().idn.strip()
                except Exception as exc:
                    self.logger.info("ASRL IDN probe failed address=%s port=%s error=%s", address, port, exc)
                if idn:
                    profile = detect_profile(idn)
                    self._messages.put(("profile", (profile, port, idn, serial_settings)))
                    results.append(f"{port}: IDN erkannt - {idn}")
                    continue

            try:
                idn, serial_settings = probe_direct_serial_idn(port, timeout_ms=500, exhaustive=False)
            except Exception as exc:
                self.logger.info("Serial IDN probe failed address=%s port=%s error=%s", address, port, exc)
                idn = ""
                serial_settings = None
            if idn:
                profile = detect_profile(idn)
                self._messages.put(("profile", (profile, port, idn, serial_settings)))
                results.append(f"{port}: IDN erkannt - {idn}")
                continue
            if not self._saved_device_for_address(port):
                self._messages.put(("serial_unknown", port))
            results.append(f"{port}: Seriell, keine IDN-Antwort")
        return results

    def _test_idn(self) -> str:
        address = self.address_var.get().strip()
        with self._open_instrument() as instrument:
            idn = instrument.info().idn
        profile = detect_profile(idn)
        serial_settings = getattr(instrument, "last_serial_settings", None)
        self._messages.put(("profile", (profile, address, idn, serial_settings)))
        if serial_settings is not None:
            self.logger.info("IDN serial settings address=%s baudrate=%s format=%s flow_control=%s terminator=%r", address, *serial_settings)
        self.logger.info("IDN address=%s idn=%s device_type=%s profile=%s %s", address, idn, profile.device_type, profile.manufacturer, profile.model_family)
        return f"{idn}\nGerätetyp: {profile.device_type}\nProfil: {profile.manufacturer} {profile.model_family}"

    def _read_value(self) -> str:
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = read_value(instrument)
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("DMM value exported workbook=%s value=%s", export.workbook_path, result.content)
        return f"Messwert gespeichert: {export.workbook_path}\n{result.content}"

    def _read_data_logger_34970a(self) -> str:
        measurement = self.data_logger_34970a_measurement_var.get().strip()
        channels = self.data_logger_34970a_channels_var.get().strip()
        baudrate = int(self.data_logger_34970a_baudrate_var.get().strip())
        serial_format = self.data_logger_34970a_serial_format_var.get().strip()
        interval_s, count = self._data_logger_timing()
        completed = 0
        started = monotonic()
        with self._open_instrument() as instrument:
            info = instrument.info()
            while not self.operation_stop_event.is_set() and (count == 0 or completed < count):
                wait_s = started + completed * interval_s - monotonic()
                if wait_s > 0 and self.operation_stop_event.wait(wait_s):
                    break
                result = read_34970a_data_logger(
                    instrument,
                    DataLogger34970AConfig(
                        measurement=measurement,
                        channels=channels,
                        baudrate=baudrate,
                        serial_format=serial_format,
                    ),
                    stop_requested=self.operation_stop_event.is_set,
                )
                export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
                completed += 1
                self.logger.info("34970A data exported workbook=%s sheet=%s measurement=%s channels=%s baudrate=%s serial_format=%s index=%s", export.workbook_path, export.sheet_name, measurement, channels, baudrate, serial_format, completed)
                if count and completed >= count:
                    break
        stopped_text = " gestoppt" if self.operation_stop_event.is_set() else " abgeschlossen"
        return f"34970A-Kanäle{stopped_text}: {self._output_path()}\nMessungen: {completed}\nMessart: {measurement}\nKanäle: {channels}"

    def _read_data_logger_34970a_plan(self) -> str:
        plan = self.data_logger_34970a_plan_var.get().strip()
        baudrate = int(self.data_logger_34970a_baudrate_var.get().strip())
        serial_format = self.data_logger_34970a_serial_format_var.get().strip()
        interval_s, count = self._data_logger_timing()
        tasks = parse_34970a_measurement_plan(plan)
        completed = 0
        started = monotonic()
        with self._open_instrument() as instrument:
            info = instrument.info()
            while not self.operation_stop_event.is_set() and (count == 0 or completed < count):
                wait_s = started + completed * interval_s - monotonic()
                if wait_s > 0 and self.operation_stop_event.wait(wait_s):
                    break
                result = read_34970a_measurement_plan(instrument, tasks, baudrate=baudrate, serial_format_value=serial_format, stop_requested=self.operation_stop_event.is_set)
                export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
                completed += 1
                self.logger.info("34970A plan exported workbook=%s sheet=%s plan=%s baudrate=%s serial_format=%s index=%s", export.workbook_path, export.sheet_name, plan, baudrate, serial_format, completed)
                if count and completed >= count:
                    break
        stopped_text = " gestoppt" if self.operation_stop_event.is_set() else " abgeschlossen"
        return f"34970A-Messplan{stopped_text}: {self._output_path()}\nMessungen: {completed}\nPlan: {plan}"

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

    def _capture_spectrum_trace(self) -> str:
        with self._open_instrument() as instrument:
            info = instrument.info()
            result = capture_waveform(instrument, info.idn, None, self.point_mode_var.get())
        export = append_result(self._output_path(), self.address_var.get().strip(), info.idn, result)
        self.logger.info("Spectrum trace exported workbook=%s sheet=%s", export.workbook_path, export.sheet_name)
        sheet_text = f"\nTabellenblatt: {export.sheet_name}" if export.sheet_name else ""
        return f"Spektrum-Trace gespeichert: {export.workbook_path}{sheet_text}"

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

    def _run_custom_sequence(self, config: CustomSequenceConfig) -> str:
        instruments: dict[str, object] = {}
        try:
            for name, address in config.devices.items():
                instruments[name] = create_sequence_instrument(address, timeout_ms=10000)
                instruments[name].open()
            result_data = run_custom_sequence(
                instruments,
                config,
                stop_requested=self.sequence_stop_event.is_set,
                progress=lambda message: self._messages.put(("progress", message)),
                step_result_export=lambda _device, info, result: self._export_custom_sequence_step_result(info, result),
            )
            first_device = next(iter(config.devices))
            result = AcquisitionResult(kind="custom sequence", file_type="csv", content=result_data.csv_content)
            export = append_result(self._output_path(), config.devices[first_device], result_data.device_infos[first_device].idn, result)
            stopped_text = " gestoppt" if result_data.stopped else " abgeschlossen"
            self.logger.info(
                "Custom sequence exported workbook=%s sheet=%s steps=%s ok=%s errors=%s devices=%s",
                export.workbook_path,
                export.sheet_name,
                result_data.actual_count,
                result_data.ok_count,
                result_data.error_count,
                ",".join(config.devices),
            )
            return f"Freier Ablauf{stopped_text}: {export.workbook_path}\nTabellenblatt: {export.sheet_name}\nSchritte: {result_data.actual_count}\nOK: {result_data.ok_count}, Fehler: {result_data.error_count}"
        finally:
            for instrument in instruments.values():
                instrument.close()
            self.sequence_running = False
            self._messages.put(("sequence_done", ""))

    def _export_custom_sequence_step_result(self, info, result: AcquisitionResult) -> str:
        export = append_result(self._output_path(), info.address, info.idn, result)
        if export.artifact_path is not None:
            return f"Datei: {export.artifact_path}"
        if export.sheet_name is not None:
            return f"Tabellenblatt: {export.sheet_name}"
        return f"Export: {export.workbook_path}"

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

    def _data_logger_timing(self) -> tuple[float, int]:
        try:
            interval_s = float(self.data_logger_34970a_interval_var.get().replace(",", "."))
            count = int(self.data_logger_34970a_count_var.get())
        except ValueError as exc:
            raise ValueError("34970A-Intervall muss eine Zahl und Anzahl eine ganze Zahl sein.") from exc
        if interval_s < 0:
            raise ValueError("34970A-Intervall darf nicht negativ sein.")
        if count < 0:
            raise ValueError("34970A-Anzahl darf nicht negativ sein.")
        return interval_s, count

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

    def _custom_sequence_config(self) -> CustomSequenceConfig:
        try:
            repeat = int(self.custom_sequence_repeat_var.get())
            pause_s = float(self.custom_sequence_pause_var.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Wiederholungen müssen ganzzahlig und Pause eine Zahl sein.") from exc
        max_voltage, max_current = self._power_supply_limits()
        variables: list[SequenceVariable] = []
        variable_name = self.custom_sequence_variable_name_var.get().strip()
        variable_start = self.custom_sequence_variable_start_var.get().strip()
        if variable_name and variable_start:
            unit = self.custom_sequence_variable_unit_var.get().strip()
            if unit not in {"frequency", "voltage", "number"}:
                unit = "number"
            variables.append(
                SequenceVariable(
                    name=variable_name,
                    start=variable_start,
                    step=self.custom_sequence_variable_step_var.get().strip(),
                    unit=unit,  # type: ignore[arg-type]
                )
            )
        return CustomSequenceConfig(
            devices=dict(self.custom_sequence_devices),
            steps=list(self.custom_sequence_steps),
            repeat=repeat,
            pause_s=pause_s,
            variables=variables,
            end_rf_off=self.custom_sequence_end_rf_off_var.get(),
            end_power_supply_off=self.custom_sequence_end_supply_off_var.get(),
            power_supply_max_voltage=max_voltage,
            power_supply_max_current=max_current,
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

    def _open_instrument(self):
        address = self.address_var.get().strip()
        if not address:
            raise ValueError("Bitte eine VISA-Adresse eintragen.")
        if address.upper().startswith("ASRL"):
            return create_sequence_instrument(address, timeout_ms=10000)
        if address.upper().startswith(("COM", "PICO::", "PICO2000A::", "SALEAE::")):
            return create_sequence_instrument(address, timeout_ms=10000)
        return VisaInstrument(address=address, timeout_ms=10000)

    def _output_path(self) -> Path:
        output = self.output_var.get().strip()
        if not output:
            raise ValueError("Bitte eine Excel-Datei auswählen.")
        return Path(output)

    def _run_worker(self, status: str, action) -> None:
        self.operation_stop_event.clear()
        self._set_operation_running(True)
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
        finally:
            self._messages.put(("operation_done", ""))

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
            elif kind == "serial_unknown":
                if isinstance(message, str):
                    self._remember_serial_unknown(message)
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
            elif kind == "operation_done":
                self._set_operation_running(False)
            elif kind == "error":
                self._set_operation_running(False)
                self.status_var.set("Fehler")
                error_message = str(message)
                self._append_log(f"Fehler: {error_message}")
                messagebox.showerror("Fehler", error_message)
            else:
                self._set_operation_running(False)
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
        self._refresh_custom_sequence_resource_combo()
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
        resource_addresses = self._resource_display_addresses(resources or [])
        numbering = self._resource_numbering_for_addresses(resource_addresses)
        for address in resource_addresses:
            label = self._resource_display_label(address, numbering)
            if label not in self.resource_display_map:
                values.append(label)
            self.resource_display_map[label] = address
        self.resource_combo.configure(values=values)

        current_address = self.address_var.get().strip()
        if current_address:
            current_label = self._resource_display_label(current_address, numbering)
            if current_label in self.resource_display_map:
                self.resource_var.set(current_label)
        elif values:
            self.resource_var.set(values[0])
            self.address_var.set(self.resource_display_map[values[0]])

    def _manual_device_resources(self) -> list[str]:
        return [
            *(port.device for port in list_direct_serial_ports()),
            *list_picoscope_resources(),
            *list_saleae_resources(),
        ]

    def _known_device_addresses(self) -> list[str]:
        return sorted(self.saved_devices, key=lambda address: self._resource_display_label(address).lower())

    def _resource_display_addresses(self, resources: list[str]) -> list[str]:
        addresses: list[str] = []
        seen: dict[str, int] = {}
        for address in [*(self._display_address_for_known_device(address) for address in self._known_device_addresses()), *dict.fromkeys(resources)]:
            canonical_address = self._canonical_address(address)
            existing_index = seen.get(canonical_address)
            if existing_index is not None:
                if self._prefer_resource_address(address, addresses[existing_index]):
                    addresses[existing_index] = address
                continue
            seen[canonical_address] = len(addresses)
            addresses.append(address)
        return addresses

    def _prefer_resource_address(self, candidate: str, current: str) -> bool:
        candidate_normalized = candidate.strip().upper()
        current_normalized = current.strip().upper()
        return candidate_normalized.startswith("ASRL") and current_normalized.startswith("COM")

    def _resource_display_label(self, address: str, numbering: dict[str, str] | None = None) -> str:
        saved = self._saved_device_for_address(address)
        if isinstance(saved, dict):
            device_type = str(saved.get("device_type", "")).strip()
            display_type = numbering.get(self._canonical_address(address), device_type) if numbering is not None else device_type
            manufacturer = str(saved.get("manufacturer", "")).strip()
            model_family = str(saved.get("model_family", "")).strip()
            description = " ".join(part for part in (display_type, manufacturer, model_family) if part and part != "Unbekannt")
            if description:
                return f"{description} - {address}"
        inferred = self._profile_for_manual_address(address)
        if inferred is not None:
            return f"{inferred.device_type} - {address}"
        return address

    def _resource_numbering_for_addresses(self, addresses: list[str]) -> dict[str, str]:
        counters: dict[str, int] = {}
        numbering: dict[str, str] = {}
        for address in dict.fromkeys(addresses):
            saved = self._saved_device_for_address(address)
            if not isinstance(saved, dict):
                continue
            role = self._sequence_role_from_saved_device(saved)
            if role == "Gerät":
                continue
            counters[role] = counters.get(role, 0) + 1
            numbering[self._canonical_address(address)] = f"{role}{counters[role]}"
        return numbering

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
        normalized = address.strip().upper()
        if normalized.startswith("COM") and normalized[3:].isdigit():
            return normalized
        if normalized.startswith("ASRL") and normalized.endswith("::INSTR"):
            port = normalized[4:-7]
            if port.isdigit():
                return f"COM{port}"
        parts = address.split("::")
        if len(parts) >= 6 and parts[-1] == "INSTR" and parts[-2].isdigit():
            return "::".join([*parts[:-2], parts[-1]])
        return address

    def _serial_port_for_address(self, address: str) -> str | None:
        normalized = address.strip().upper()
        if normalized.startswith("COM") and normalized[3:].isdigit():
            return normalized
        if normalized.startswith("ASRL") and normalized.endswith("::INSTR"):
            port = normalized[4:-7]
            if port.isdigit():
                return f"COM{port}"
        return None

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
        data_logger_enabled = profile.key == "keysight_34970a" or "34970" in profile.model_family or profile.device_type == "Datenlogger"
        spectrum_enabled = "spektrum" in profile.device_type.lower() or profile.key in {"hp_4395a", "hp_8591a", "hp_e740", "hp_agilent_e4402b", "rs_hameg_hms"}
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
        self._set_section_visible("data_logger", data_logger_enabled)
        self._set_section_visible("spectrum", spectrum_enabled)
        self._set_section_visible("generator", generator_enabled)
        self._set_section_visible("power_supply", power_supply_enabled)
        self._set_widgets_enabled(self._scope_widgets, scope_enabled)
        self._set_widgets_enabled(self._dmm_widgets, dmm_enabled)
        self._set_widgets_enabled(self._timed_widgets, timed_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_dmm_widgets, dmm_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_scope_widgets, scope_measurement_enabled and not self.timed_running)
        self._set_widgets_enabled(self._timed_stop_widgets, self.timed_running)
        self._set_widgets_enabled(self._vna_widgets, vna_enabled)
        self._set_widgets_enabled(self._data_logger_widgets, data_logger_enabled and not self.operation_running)
        self._set_widgets_enabled(self._data_logger_stop_widgets, data_logger_enabled and self.operation_running)
        self._set_widgets_enabled(self._spectrum_widgets, spectrum_enabled)
        self._set_widgets_enabled(self._spectrum_screenshot_widgets, spectrum_enabled and screenshot_enabled)
        self._set_widgets_enabled(self._screenshot_widgets, screenshot_enabled)
        self._set_widgets_enabled(self._generator_widgets, generator_enabled)
        self._set_widgets_enabled(self._power_supply_widgets, power_supply_enabled)
        if self.sequence_running:
            self._set_sequence_running(True)
        if self.switch_running:
            self._set_switch_running(True)

    def _apply_profile_message(self, message: object) -> None:
        if isinstance(message, tuple) and len(message) in {3, 4}:
            profile, address, idn = message[:3]
            serial_settings = message[3] if len(message) == 4 else None
            if isinstance(profile, DeviceProfile) and isinstance(address, str) and isinstance(idn, str):
                self._remember_device(address, idn, profile)
                if self._is_serial_settings(serial_settings):
                    self._remember_serial_settings(address, serial_settings)
                self._apply_profile(profile)
                return
        if isinstance(message, DeviceProfile):
            self._apply_profile(message)

    def _apply_saved_profile_for_address(self) -> None:
        address = self.address_var.get().strip()
        saved = self._saved_device_for_address(address)
        if isinstance(saved, dict):
            serial_settings = self._serial_settings_from_saved_device(saved)
            if serial_settings is not None:
                set_preferred_serial_scpi_settings(serial_settings)
            self._apply_profile(self._profile_from_settings(saved))
        else:
            self._apply_profile(self._profile_for_manual_address(address) or UNKNOWN_PROFILE)

    def _profile_for_manual_address(self, address: str) -> DeviceProfile | None:
        normalized = address.strip().upper()
        if normalized.startswith(("PICO::", "PICO2000A::")):
            return DeviceProfile("Pico Technology", "PicoScope", "PicoScope", key="picoscope")
        if normalized.startswith("SALEAE::"):
            return DeviceProfile("Saleae", "Logic 2 Automation", "Saleae", key="saleae_logic2")
        if normalized.startswith("COM") and normalized[3:].isdigit():
            return self._serial_unknown_profile()
        return None

    def _serial_unknown_profile(self) -> DeviceProfile:
        return DeviceProfile("Unbekannt", "Direkter COM-Port", "Seriell", key="direct_serial")

    def _set_operation_running(self, running: bool) -> None:
        self.operation_running = running
        data_logger_enabled = self.current_profile.key == "keysight_34970a" or "34970" in self.current_profile.model_family or self.current_profile.device_type == "Datenlogger"
        self._set_widgets_enabled(self._data_logger_widgets, data_logger_enabled and not running)
        self._set_widgets_enabled(self._data_logger_stop_widgets, data_logger_enabled and running)

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
        self._refresh_custom_sequence_resource_combo()
        self._save_settings()

    def _remember_serial_unknown(self, address: str) -> None:
        if not address or self._saved_device_for_address(address):
            return
        self._remember_device(address, "Serielles Gerät ohne IDN", self._serial_unknown_profile())

    def _remember_serial_settings(self, address: str, settings: tuple[int, str, str, str]) -> None:
        saved = self._saved_device_for_address(address)
        if not isinstance(saved, dict):
            return
        baudrate, serial_format, flow_control, terminator = settings
        saved["serial_settings"] = {
            "baudrate": baudrate,
            "format": serial_format,
            "flow_control": flow_control,
            "terminator": terminator,
        }
        self.saved_devices[self._canonical_address(address)] = saved
        if str(saved.get("key", "")) == "keysight_34970a":
            self.data_logger_34970a_baudrate_var.set(str(baudrate))
            self.data_logger_34970a_serial_format_var.set(serial_format)
        set_preferred_serial_scpi_settings(settings)
        self._save_settings()

    def _serial_settings_from_saved_device(self, saved: dict[str, object]) -> tuple[int, str, str, str] | None:
        settings = saved.get("serial_settings")
        if not isinstance(settings, dict):
            return None
        try:
            baudrate = int(settings.get("baudrate", 9600))
            serial_format = str(settings.get("format", "8N1"))
            flow_control = str(settings.get("flow_control", "none"))
            terminator = str(settings.get("terminator", "\n"))
        except (TypeError, ValueError):
            return None
        return (baudrate, serial_format, flow_control, terminator)

    def _is_serial_settings(self, value: object) -> bool:
        return isinstance(value, tuple) and len(value) == 4 and isinstance(value[0], int) and all(isinstance(part, str) for part in value[1:])

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
            self._set_widgets_enabled(self._data_logger_widgets, False)
            self._set_widgets_enabled(self._data_logger_stop_widgets, False)
            self._set_widgets_enabled(self._spectrum_widgets, False)
            self._set_widgets_enabled(self._spectrum_screenshot_widgets, False)
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
            self._set_widgets_enabled(self._data_logger_widgets, False)
            self._set_widgets_enabled(self._data_logger_stop_widgets, False)
            self._set_widgets_enabled(self._spectrum_widgets, False)
            self._set_widgets_enabled(self._spectrum_screenshot_widgets, False)
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

    def _step_from_settings(self, data: dict) -> SequenceStep:
        params = data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        return SequenceStep(device=str(data.get("device", "")), action=str(data.get("action", "")), params=dict(params))

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
            "data_logger_34970a_measurement": self.data_logger_34970a_measurement_var.get(),
            "data_logger_34970a_channels": self.data_logger_34970a_channels_var.get(),
            "data_logger_34970a_plan": self.data_logger_34970a_plan_var.get(),
            "data_logger_34970a_baudrate": self.data_logger_34970a_baudrate_var.get(),
            "data_logger_34970a_serial_format": self.data_logger_34970a_serial_format_var.get(),
            "data_logger_34970a_interval": self.data_logger_34970a_interval_var.get(),
            "data_logger_34970a_count": self.data_logger_34970a_count_var.get(),
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
            "custom_sequence_devices": self.custom_sequence_devices,
            "custom_sequence_steps": [
                {"device": step.device, "action": step.action, "params": step.params}
                for step in self.custom_sequence_steps
            ],
            "custom_sequence_repeat": self.custom_sequence_repeat_var.get(),
            "custom_sequence_pause": self.custom_sequence_pause_var.get(),
            "custom_sequence_variable_name": self.custom_sequence_variable_name_var.get(),
            "custom_sequence_variable_unit": self.custom_sequence_variable_unit_var.get(),
            "custom_sequence_variable_start": self.custom_sequence_variable_start_var.get(),
            "custom_sequence_variable_step": self.custom_sequence_variable_step_var.get(),
            "custom_sequence_end_rf_off": self.custom_sequence_end_rf_off_var.get(),
            "custom_sequence_end_supply_off": self.custom_sequence_end_supply_off_var.get(),
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


def _format_step_params(params: dict[str, object]) -> str:
    return "; ".join(f"{key}={value}" for key, value in params.items())


def _read_sequence_data_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Ablauf-Datei muss ein JSON-Objekt enthalten.")
    return data


def _write_sequence_data_file(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
