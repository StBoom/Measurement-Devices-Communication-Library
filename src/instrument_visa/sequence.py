from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import monotonic, sleep
from typing import Callable, Literal

try:
    import serial
    import serial.tools.list_ports as serial_list_ports
except ImportError:  # pragma: no cover - dependency error is reported at runtime
    serial = None  # type: ignore[assignment]
    serial_list_ports = None  # type: ignore[assignment]

from .acquisition import (
    AcquisitionResult,
    capture_screenshot,
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
from .picoscope_client import PicoScopeAnalogConfig, PicoScopeDigitalConfig, create_picoscope_instrument, is_picoscope_address
from .visa_client import InstrumentInfo, VisaInstrument


MAX_SWEEP_POINTS = 10000
ProgressCallback = Callable[[str], None]
StopCallback = Callable[[], bool]
StepResultExportCallback = Callable[[str, InstrumentInfo, AcquisitionResult], str]


def parse_json_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"Expected boolean value, got {value!r}.")


@dataclass(frozen=True)
class FrequencySweepConfig:
    start_frequency: str
    stop_frequency: str
    step_frequency: str
    power: str
    max_power_dbm: float
    settle_s: float
    measurement_mode: str
    scope_measurement: str = "Vpp"
    scope_channel: int = 1
    rf_off_before_change: bool = True
    rf_off_at_end: bool = True


@dataclass(frozen=True)
class FrequencySweepResult:
    csv_content: str
    generator_info: InstrumentInfo
    measurement_info: InstrumentInfo
    actual_count: int
    ok_count: int
    error_count: int
    stopped: bool


@dataclass(frozen=True)
class VoltageSweepConfig:
    start_voltage: str
    stop_voltage: str
    step_voltage: str
    current_limit: str
    channel: int
    max_voltage: float
    max_current: float
    settle_s: float
    measurement_mode: str
    scope_measurement: str = "Vpp"
    scope_channel: int = 1
    output_off_at_end: bool = True


@dataclass(frozen=True)
class VoltageSweepResult:
    csv_content: str
    power_supply_info: InstrumentInfo
    measurement_info: InstrumentInfo
    actual_count: int
    ok_count: int
    error_count: int
    stopped: bool


@dataclass(frozen=True)
class TimedSwitchConfig:
    source_type: str
    on_s: float
    off_s: float
    repetitions: int
    end_off: bool = True
    setup_before_start: bool = False
    generator_frequency: str = "100 MHz"
    generator_power: str = "-30 dBm"
    generator_max_power_dbm: float = 0.0
    power_supply_channel: int = 1
    power_supply_voltage: str = "1 V"
    power_supply_current: str = "0.1 A"
    power_supply_max_voltage: float = 5.0
    power_supply_max_current: float = 0.5
    power_supply_switch_mode: str = "master"


@dataclass(frozen=True)
class TimedSwitchResult:
    csv_content: str
    source_info: InstrumentInfo
    actual_count: int
    ok_count: int
    error_count: int
    stopped: bool


@dataclass(frozen=True)
class SequenceVariable:
    name: str
    start: str = ""
    step: str = ""
    unit: Literal["frequency", "voltage", "number"] = "number"


@dataclass(frozen=True)
class SequenceStep:
    device: str
    action: str
    params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CustomSequenceConfig:
    devices: dict[str, str]
    steps: list[SequenceStep]
    repeat: int = 1
    pause_s: float = 0.0
    variables: list[SequenceVariable] = field(default_factory=list)
    end_rf_off: bool = True
    end_power_supply_off: bool = False
    power_supply_max_voltage: float = 32.0
    power_supply_max_current: float = 10.0


@dataclass(frozen=True)
class CustomSequenceResult:
    csv_content: str
    device_infos: dict[str, InstrumentInfo]
    actual_count: int
    ok_count: int
    error_count: int
    stopped: bool


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str


@dataclass(frozen=True)
class ParallelTask:
    device: str
    action: Literal["dmm", "scope", "serial"]
    measurement: str = "Vpp"
    channel: int = 1
    baudrate: int = 115200
    serial_format: str = "8N1"


def run_frequency_sweep(
    generator: VisaInstrument,
    measurement_instrument: VisaInstrument,
    config: FrequencySweepConfig,
    stop_requested: StopCallback | None = None,
    progress: ProgressCallback | None = None,
) -> FrequencySweepResult:
    stop_requested = stop_requested or (lambda: False)
    progress = progress or (lambda message: None)
    points = frequency_points(config.start_frequency, config.stop_frequency, config.step_frequency)
    if not points:
        raise ValueError("Sweep benötigt mindestens einen Frequenzpunkt.")
    requested_power_dbm = parse_dbm(config.power)
    if requested_power_dbm > config.max_power_dbm:
        raise ValueError(f"Requested power {requested_power_dbm:g} dBm exceeds max power {config.max_power_dbm:g} dBm")

    generator_info = generator.info()
    measurement_info = measurement_instrument.info()
    rows: list[list[object]] = [
        [
            "SetFrequencyHz",
            "Index",
            "Timestamp",
            "ElapsedSeconds",
            "GeneratorAddress",
            "GeneratorIDN",
            "MeasurementAddress",
            "MeasurementIDN",
            "SetPower",
            "MeasurementMode",
            "Measurement",
            "Channel",
            "Value",
            "Status",
        ]
    ]
    started_at = datetime.now()
    started = monotonic()
    ok_count = 0
    error_count = 0

    try:
        for index, frequency_hz in enumerate(points, start=1):
            if stop_requested():
                break

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            frequency_command = format_frequency_hz(frequency_hz)
            measurement_label = "DMM :READ?"
            channel_value: str | int = ""
            value: object = ""
            status = "OK"
            try:
                set_signal_generator(
                    generator,
                    generator_info.idn,
                    frequency_command,
                    config.power,
                    True,
                    config.max_power_dbm,
                    config.rf_off_before_change,
                )
            except Exception as exc:
                status = f"GENERATOR_ERROR: {exc}"
                error_count += 1
                elapsed_s = monotonic() - started
                rows.append(
                    [
                        f"{frequency_hz:.6f}",
                        index,
                        timestamp,
                        f"{elapsed_s:.3f}",
                        generator_info.address,
                        generator_info.idn,
                        measurement_info.address,
                        measurement_info.idn,
                        config.power,
                        config.measurement_mode.upper(),
                        measurement_label,
                        channel_value,
                        value,
                        status,
                    ]
                )
                progress(f"Ablauf {index}/{len(points)}: {status}")
                break

            try:
                if config.settle_s > 0:
                    _sleep_interruptible(config.settle_s, stop_requested)
                if stop_requested():
                    break
                if config.measurement_mode == "dmm":
                    result = read_value(measurement_instrument)
                elif config.measurement_mode == "scope":
                    result = read_scope_measurement(measurement_instrument, config.scope_measurement, config.scope_channel, measurement_info.idn)
                    measurement_label = config.scope_measurement
                    channel_value = f"CH{config.scope_channel}"
                else:
                    raise ValueError(f"Unsupported sweep measurement mode: {config.measurement_mode}")
                value = result.content
                ok_count += 1
            except Exception as exc:
                status = f"ERROR: {exc}"
                error_count += 1

            elapsed_s = monotonic() - started
            rows.append(
                [
                    f"{frequency_hz:.6f}",
                    index,
                    timestamp,
                    f"{elapsed_s:.3f}",
                    generator_info.address,
                    generator_info.idn,
                    measurement_info.address,
                    measurement_info.idn,
                    config.power,
                    config.measurement_mode.upper(),
                    measurement_label,
                    channel_value,
                    value,
                    status,
                ]
            )
            progress(f"Ablauf {index}/{len(points)}: {format_frequency_hz(frequency_hz)} -> {value if status == 'OK' else status}")
    finally:
        if config.rf_off_at_end or stop_requested() or error_count:
            try:
                set_signal_generator_rf_output(generator, generator_info.idn, False)
                rows.append(_frequency_cleanup_row(started, generator_info, measurement_info, config, "FINAL_OFF"))
            except Exception as exc:
                error_count += 1
                rows.append(_frequency_cleanup_row(started, generator_info, measurement_info, config, f"FINAL_OFF_ERROR: {exc}"))
                progress(f"RF-Aus am Ende fehlgeschlagen: {exc}")

    actual_count = _data_row_count(rows)

    rows.extend(
        [
            [],
            ["Summary", ""],
            ["StartedAt", started_at.strftime("%Y-%m-%d %H:%M:%S")],
            ["FinishedAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["RequestedStartFrequencyHz", f"{parse_frequency_hz(config.start_frequency):.6f}"],
            ["RequestedStopFrequencyHz", f"{parse_frequency_hz(config.stop_frequency):.6f}"],
            ["RequestedStepFrequencyHz", f"{parse_frequency_hz(config.step_frequency):.6f}"],
            ["RequestedPower", config.power],
            ["SettleSeconds", f"{config.settle_s:.3f}"],
            ["ActualCount", actual_count],
            ["OkCount", ok_count],
            ["ErrorCount", error_count],
            ["StoppedByUser", "Yes" if stop_requested() else "No"],
        ]
    )
    return FrequencySweepResult(
        csv_content=_csv_rows(rows),
        generator_info=generator_info,
        measurement_info=measurement_info,
        actual_count=actual_count,
        ok_count=ok_count,
        error_count=error_count,
        stopped=stop_requested(),
    )


def run_voltage_sweep(
    power_supply: VisaInstrument,
    measurement_instrument: VisaInstrument,
    config: VoltageSweepConfig,
    stop_requested: StopCallback | None = None,
    progress: ProgressCallback | None = None,
) -> VoltageSweepResult:
    stop_requested = stop_requested or (lambda: False)
    progress = progress or (lambda message: None)
    points = voltage_points(config.start_voltage, config.stop_voltage, config.step_voltage)
    if not points:
        raise ValueError("Sweep benötigt mindestens einen Spannungspunkt.")
    current_limit = parse_ampere(config.current_limit)
    if max(points) > config.max_voltage:
        raise ValueError(f"Requested voltage {max(points):g} V exceeds max voltage {config.max_voltage:g} V")
    if current_limit > config.max_current:
        raise ValueError(f"Requested current {current_limit:g} A exceeds max current {config.max_current:g} A")

    power_supply_info = power_supply.info()
    measurement_info = measurement_instrument.info()
    rows: list[list[object]] = [
        [
            "SetVoltageV",
            "Index",
            "Timestamp",
            "ElapsedSeconds",
            "PowerSupplyAddress",
            "PowerSupplyIDN",
            "MeasurementAddress",
            "MeasurementIDN",
            "Channel",
            "SetCurrentLimit",
            "SupplyVoltageMeasured",
            "SupplyCurrentMeasured",
            "MeasurementMode",
            "Measurement",
            "MeasurementChannel",
            "Value",
            "Status",
        ]
    ]
    started_at = datetime.now()
    started = monotonic()
    ok_count = 0
    error_count = 0

    try:
        for index, voltage in enumerate(points, start=1):
            if stop_requested():
                break

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            voltage_command = format_decimal_value(voltage, "V")
            measurement_label = "DMM :READ?"
            measurement_channel: str | int = ""
            value: object = ""
            status = "OK"
            supply_voltage = ""
            supply_current = ""
            try:
                set_power_supply(
                    power_supply,
                    power_supply_info.idn,
                    config.channel,
                    voltage_command,
                    config.current_limit,
                    True,
                    config.max_voltage,
                    config.max_current,
                )
            except Exception as exc:
                status = f"POWER_SUPPLY_ERROR: {exc}"
                error_count += 1
                elapsed_s = monotonic() - started
                rows.append(
                    [
                        f"{voltage:.6f}",
                        index,
                        timestamp,
                        f"{elapsed_s:.3f}",
                        power_supply_info.address,
                        power_supply_info.idn,
                        measurement_info.address,
                        measurement_info.idn,
                        config.channel,
                        config.current_limit,
                        supply_voltage,
                        supply_current,
                        config.measurement_mode.upper(),
                        measurement_label,
                        measurement_channel,
                        value,
                        status,
                    ]
                )
                progress(f"Ablauf {index}/{len(points)}: {status}")
                break

            try:
                supply_settings = read_power_supply_settings(power_supply, power_supply_info.idn, config.channel)
                supply_voltage = supply_settings.voltage_measured
                supply_current = supply_settings.current_measured
                if config.settle_s > 0:
                    _sleep_interruptible(config.settle_s, stop_requested)
                if stop_requested():
                    break
                if config.measurement_mode == "dmm":
                    result = read_value(measurement_instrument)
                elif config.measurement_mode == "scope":
                    result = read_scope_measurement(measurement_instrument, config.scope_measurement, config.scope_channel, measurement_info.idn)
                    measurement_label = config.scope_measurement
                    measurement_channel = f"CH{config.scope_channel}"
                else:
                    raise ValueError(f"Unsupported sweep measurement mode: {config.measurement_mode}")
                value = result.content
                ok_count += 1
            except Exception as exc:
                status = f"ERROR: {exc}"
                error_count += 1

            elapsed_s = monotonic() - started
            rows.append(
                [
                    f"{voltage:.6f}",
                    index,
                    timestamp,
                    f"{elapsed_s:.3f}",
                    power_supply_info.address,
                    power_supply_info.idn,
                    measurement_info.address,
                    measurement_info.idn,
                        config.channel,
                        config.current_limit,
                        supply_voltage,
                        supply_current,
                        config.measurement_mode.upper(),
                    measurement_label,
                    measurement_channel,
                    value,
                    status,
                ]
            )
            progress(f"Ablauf {index}/{len(points)}: {voltage_command} -> {value if status == 'OK' else status}")
    finally:
        if config.output_off_at_end or stop_requested() or error_count:
            try:
                set_power_supply_master_output(power_supply, power_supply_info.idn, False, config.channel)
                rows.append(_voltage_cleanup_row(started, power_supply_info, measurement_info, config, "FINAL_OFF"))
            except Exception as exc:
                error_count += 1
                rows.append(_voltage_cleanup_row(started, power_supply_info, measurement_info, config, f"FINAL_OFF_ERROR: {exc}"))
                progress(f"Netzgerät-Aus am Ende fehlgeschlagen: {exc}")

    actual_count = _data_row_count(rows)
    rows.extend(
        [
            [],
            ["Summary", ""],
            ["StartedAt", started_at.strftime("%Y-%m-%d %H:%M:%S")],
            ["FinishedAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["RequestedStartVoltageV", f"{parse_voltage(config.start_voltage):.6f}"],
            ["RequestedStopVoltageV", f"{parse_voltage(config.stop_voltage):.6f}"],
            ["RequestedStepVoltageV", f"{parse_voltage(config.step_voltage):.6f}"],
            ["RequestedCurrentLimit", config.current_limit],
            ["PowerSupplyChannel", config.channel],
            ["SettleSeconds", f"{config.settle_s:.3f}"],
            ["ActualCount", actual_count],
            ["OkCount", ok_count],
            ["ErrorCount", error_count],
            ["StoppedByUser", "Yes" if stop_requested() else "No"],
        ]
    )
    return VoltageSweepResult(
        csv_content=_csv_rows(rows),
        power_supply_info=power_supply_info,
        measurement_info=measurement_info,
        actual_count=actual_count,
        ok_count=ok_count,
        error_count=error_count,
        stopped=stop_requested(),
    )


def run_timed_switch(
    source: VisaInstrument,
    config: TimedSwitchConfig,
    stop_requested: StopCallback | None = None,
    progress: ProgressCallback | None = None,
) -> TimedSwitchResult:
    stop_requested = stop_requested or (lambda: False)
    progress = progress or (lambda message: None)
    _validate_timed_switch_config(config)
    source_info = source.info()
    rows: list[list[object]] = [["Index", "Timestamp", "ElapsedSeconds", "SourceType", "Address", "IDN", "State", "DurationSeconds", "Status"]]
    started_at = datetime.now()
    started = monotonic()
    ok_count = 0
    error_count = 0

    try:
        if config.setup_before_start:
            _setup_switch_source(source, source_info.idn, config)
        else:
            _validate_current_switch_source(source, source_info.idn, config)
        for index in range(1, config.repetitions + 1):
            if stop_requested():
                break
            try:
                _switch_source(source, source_info.idn, config, True)
                rows.append(_switch_row(index, started, source_info, config.source_type, "ON", config.on_s, "OK"))
                ok_count += 1
                progress(f"Schalten {index}/{config.repetitions}: ON")
                _sleep_interruptible(config.on_s, stop_requested)
                if stop_requested():
                    break
                _switch_source(source, source_info.idn, config, False)
                rows.append(_switch_row(index, started, source_info, config.source_type, "OFF", config.off_s, "OK"))
                ok_count += 1
                progress(f"Schalten {index}/{config.repetitions}: OFF")
                _sleep_interruptible(config.off_s, stop_requested)
            except Exception as exc:
                rows.append(_switch_row(index, started, source_info, config.source_type, "ERROR", 0, f"ERROR: {exc}"))
                error_count += 1
                break
    finally:
        if config.end_off or stop_requested() or error_count:
            try:
                _switch_source(source, source_info.idn, config, False)
                rows.append(_switch_row(0, started, source_info, config.source_type, "FINAL_OFF", 0, "OK"))
            except Exception as exc:
                error_count += 1
                rows.append(_switch_row(0, started, source_info, config.source_type, "FINAL_OFF", 0, f"FINAL_OFF_ERROR: {exc}"))
                progress(f"Ausschalten am Ende fehlgeschlagen: {exc}")

    actual_count = _data_row_count(rows)
    rows.extend(
        [
            [],
            ["Summary", ""],
            ["StartedAt", started_at.strftime("%Y-%m-%d %H:%M:%S")],
            ["FinishedAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["RequestedRepetitions", config.repetitions],
            ["OnSeconds", f"{config.on_s:.3f}"],
            ["OffSeconds", f"{config.off_s:.3f}"],
            ["EndOff", "Yes" if config.end_off else "No"],
            ["ActualEvents", actual_count],
            ["OkCount", ok_count],
            ["ErrorCount", error_count],
            ["StoppedByUser", "Yes" if stop_requested() else "No"],
        ]
    )
    return TimedSwitchResult(_csv_rows(rows), source_info, actual_count, ok_count, error_count, stop_requested())


def run_custom_sequence(
    instruments: dict[str, object],
    config: CustomSequenceConfig,
    stop_requested: StopCallback | None = None,
    progress: ProgressCallback | None = None,
    step_result_export: StepResultExportCallback | None = None,
) -> CustomSequenceResult:
    stop_requested = stop_requested or (lambda: False)
    progress = progress or (lambda message: None)
    _validate_custom_sequence(config)
    missing_devices = [name for name in config.devices if name not in instruments]
    if missing_devices:
        raise ValueError("Fehlende geöffnete Geräte: " + ", ".join(missing_devices))

    device_infos = {name: _custom_sequence_device_info(name, config, instruments[name]) for name in config.devices}
    rows: list[list[object]] = [["Run", "Step", "Timestamp", "ElapsedSeconds", "Device", "Address", "IDN", "Action", "Parameters", "Value", "Status"]]
    started_at = datetime.now()
    started = monotonic()
    ok_count = 0
    error_count = 0
    executed_steps = 0

    try:
        for run_index in range(1, config.repeat + 1):
            if stop_requested():
                break
            variables = _sequence_variables_for_run(config.variables, run_index)
            for step_index, step in enumerate(config.steps, start=1):
                if stop_requested():
                    break
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                value: object = ""
                status = "OK"
                params = _resolve_step_params(step.params, variables)
                address = ""
                idn = ""
                try:
                    value = _execute_custom_sequence_step(step, params, instruments, device_infos, config, stop_requested, step_result_export)
                    if isinstance(value, AcquisitionResult):
                        value = _custom_step_result_value(step, value, device_infos, step_result_export)
                    ok_count += 1
                except Exception as exc:
                    status = f"ERROR: {exc}"
                    error_count += 1
                if step.device:
                    address = device_infos[step.device].address
                    idn = device_infos[step.device].idn
                executed_steps += 1
                rows.append([run_index, step_index, timestamp, f"{monotonic() - started:.3f}", step.device, address, idn, step.action, _format_params(params), value, status])
                progress(f"Ablauf {run_index}/{config.repeat}, Schritt {step_index}/{len(config.steps)}: {step.action} -> {value if status == 'OK' else status}")
                if status != "OK":
                    break
            if error_count or stop_requested():
                break
            if config.pause_s > 0 and run_index < config.repeat:
                _sleep_interruptible(config.pause_s, stop_requested)
    finally:
        cleanup_rows, cleanup_errors = _custom_sequence_cleanup(config, instruments, device_infos, started, stop_requested)
        rows.extend(cleanup_rows)
        error_count += cleanup_errors

    rows.extend(
        [
            [],
            ["Summary", ""],
            ["StartedAt", started_at.strftime("%Y-%m-%d %H:%M:%S")],
            ["FinishedAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["RequestedRuns", config.repeat],
            ["StepsPerRun", len(config.steps)],
            ["PauseSeconds", f"{config.pause_s:.3f}"],
            ["ActualSteps", executed_steps],
            ["OkCount", ok_count],
            ["ErrorCount", error_count],
            ["StoppedByUser", "Yes" if stop_requested() else "No"],
        ]
    )
    return CustomSequenceResult(_csv_rows(rows), device_infos, executed_steps, ok_count, error_count, stop_requested())


def frequency_points(start: str, stop: str, step: str) -> list[float]:
    start_hz = parse_frequency_hz(start)
    stop_hz = parse_frequency_hz(stop)
    step_hz = parse_frequency_hz(step)
    if step_hz <= 0:
        raise ValueError("Schrittweite muss größer als 0 sein.")
    if stop_hz < start_hz:
        raise ValueError("Stopfrequenz muss größer oder gleich Startfrequenz sein.")
    point_count = int((stop_hz - start_hz) // step_hz) + 1
    if point_count > MAX_SWEEP_POINTS:
        raise ValueError(f"Sweep hat {point_count} Punkte; maximal erlaubt sind {MAX_SWEEP_POINTS}.")

    points: list[float] = []
    value = start_hz
    epsilon = step_hz / 1_000_000
    while value <= stop_hz + epsilon:
        points.append(round(value, 6))
        value += step_hz
    if points[-1] > stop_hz + epsilon:
        points.pop()
    return points


def voltage_points(start: str, stop: str, step: str) -> list[float]:
    start_v = parse_voltage(start)
    stop_v = parse_voltage(stop)
    step_v = parse_voltage(step)
    if step_v <= 0:
        raise ValueError("Spannungsschritt muss größer als 0 sein.")
    if stop_v < start_v:
        raise ValueError("Stopspannung muss größer oder gleich Startspannung sein.")
    point_count = int((stop_v - start_v) // step_v) + 1
    if point_count > MAX_SWEEP_POINTS:
        raise ValueError(f"Sweep hat {point_count} Punkte; maximal erlaubt sind {MAX_SWEEP_POINTS}.")

    points: list[float] = []
    value = start_v
    epsilon = step_v / 1_000_000
    while value <= stop_v + epsilon:
        points.append(round(value, 6))
        value += step_v
    if points[-1] > stop_v + epsilon:
        points.pop()
    return points


def _validate_custom_sequence(config: CustomSequenceConfig) -> None:
    if config.repeat <= 0:
        raise ValueError("Wiederholungen müssen größer als 0 sein.")
    if config.pause_s < 0:
        raise ValueError("Pause darf nicht negativ sein.")
    if config.power_supply_max_voltage <= 0 or config.power_supply_max_current <= 0:
        raise ValueError("Netzgerät-Grenzwerte müssen größer als 0 sein.")
    if not config.steps:
        raise ValueError("Ablauf benötigt mindestens einen Schritt.")
    if not config.devices:
        raise ValueError("Ablauf benötigt mindestens ein Gerät.")
    for name, address in config.devices.items():
        if not name.strip():
            raise ValueError("Gerätename darf nicht leer sein.")
        if not address.strip():
            raise ValueError(f"Adresse für {name} darf nicht leer sein.")
    for step in config.steps:
        if step.action not in {"wait", "parallel_phase"} and step.device not in config.devices:
            raise ValueError(f"Unbekanntes Gerät im Ablauf: {step.device}")
        _validate_custom_sequence_step(step)
    for variable in config.variables:
        if not variable.name.strip():
            raise ValueError("Variablenname darf nicht leer sein.")
        _variable_value_for_run(variable, 1)


class DirectSerialInstrument:
    def __init__(self, address: str, timeout_ms: int = 10000) -> None:
        self.address = address
        self.timeout_ms = timeout_ms

    def open(self) -> None:
        return

    def close(self) -> None:
        return

    def info(self) -> InstrumentInfo:
        return InstrumentInfo(address=self.address, idn="Direkter COM-Port")


def create_sequence_instrument(address: str, timeout_ms: int = 10000) -> VisaInstrument | DirectSerialInstrument:
    if is_picoscope_address(address):
        return create_picoscope_instrument(address, timeout_ms=timeout_ms)
    if _is_direct_serial_address(address):
        return DirectSerialInstrument(address, timeout_ms)
    return VisaInstrument(address, timeout_ms=timeout_ms)


def _custom_sequence_device_info(name: str, config: CustomSequenceConfig, instrument: object) -> InstrumentInfo:
    try:
        return instrument.info()
    except Exception:
        if _device_only_uses_serial_log(name, config):
            return InstrumentInfo(address=str(getattr(instrument, "address", config.devices.get(name, ""))), idn="Serieller Log ohne IDN")
        raise


def _device_only_uses_serial_log(name: str, config: CustomSequenceConfig) -> bool:
    device_steps = [step for step in config.steps if step.device == name]
    return bool(device_steps) and all(step.action == "serial_log" for step in device_steps)


def _is_direct_serial_address(address: str) -> bool:
    normalized = address.strip().upper()
    return normalized.startswith("COM") and normalized[3:].isdigit()


def list_direct_serial_ports() -> list[SerialPortInfo]:
    if serial_list_ports is None:
        return []
    try:
        return [SerialPortInfo(device=str(port.device), description=str(port.description or "")) for port in serial_list_ports.comports()]
    except Exception:
        return []


def _execute_custom_sequence_step(
    step: SequenceStep,
    params: dict[str, object],
    instruments: dict[str, object],
    device_infos: dict[str, InstrumentInfo],
    config: CustomSequenceConfig,
    stop_requested: StopCallback,
    step_result_export: StepResultExportCallback | None,
) -> object:
    if step.action == "wait":
        seconds = _float_param(params, "seconds", 0.0)
        if seconds < 0:
            raise ValueError("Wartezeit darf nicht negativ sein.")
        _sleep_interruptible(seconds, stop_requested)
        return f"{seconds:.3f} s"
    if step.action == "parallel_phase":
        duration_s = _float_param(params, "duration_s", 1.0)
        interval_s = _float_param(params, "interval_s", 1.0)
        tasks = parse_parallel_tasks(str(params.get("tasks", "")))
        return run_parallel_phase(instruments, device_infos, duration_s, interval_s, tasks, stop_requested, step_result_export)

    instrument = instruments[step.device]
    info = device_infos[step.device]
    if step.action == "generator_set_frequency":
        frequency = _string_param(params, "frequency")
        power = _string_param(params, "power")
        max_power = _float_param(params, "max_power_dbm", 0.0)
        rf_enabled = _bool_param(params, "rf", True)
        rf_off_before_change = _bool_param(params, "rf_off_before_change", True)
        set_signal_generator(instrument, info.idn, frequency, power, rf_enabled, max_power, rf_off_before_change)
        return frequency
    if step.action == "generator_set_power":
        settings = read_signal_generator_settings(instrument, info.idn)
        power = _string_param(params, "power")
        max_power = _float_param(params, "max_power_dbm", 0.0)
        rf_enabled = _bool_param(params, "rf", settings.rf_output.upper() == "ON")
        rf_off_before_change = _bool_param(params, "rf_off_before_change", True)
        set_signal_generator(instrument, info.idn, settings.frequency, power, rf_enabled, max_power, rf_off_before_change)
        return power
    if step.action == "generator_rf":
        enabled = _bool_param(params, "enabled", False)
        set_signal_generator_rf_output(instrument, info.idn, enabled)
        return "ON" if enabled else "OFF"
    if step.action == "power_supply_set":
        channel = _int_param(params, "channel", 1)
        voltage = _string_param(params, "voltage")
        current = _string_param(params, "current")
        enabled = _bool_param(params, "output", True)
        max_voltage = _float_param(params, "max_voltage", config.power_supply_max_voltage)
        max_current = _float_param(params, "max_current", config.power_supply_max_current)
        set_power_supply(instrument, info.idn, channel, voltage, current, enabled, max_voltage, max_current)
        return voltage
    if step.action == "power_supply_output":
        channel = _int_param(params, "channel", 1)
        enabled = _bool_param(params, "enabled", False)
        set_power_supply_output(instrument, info.idn, channel, enabled)
        return "ON" if enabled else "OFF"
    if step.action == "power_supply_master_output":
        channel = _int_param(params, "channel", 1)
        enabled = _bool_param(params, "enabled", False)
        set_power_supply_master_output(instrument, info.idn, enabled, channel)
        return "ON" if enabled else "OFF"
    if step.action == "dmm_read":
        return read_value(instrument).content
    if step.action == "scope_measure":
        measurement = _string_param(params, "measurement")
        channel = _int_param(params, "channel", 1)
        return read_scope_measurement(instrument, measurement, channel, info.idn).content
    if step.action == "capture_waveform":
        channels = _channels_param(params.get("channels", ""))
        point_mode = str(params.get("point_mode", "RAW")).strip() or "RAW"
        return capture_waveform(instrument, info.idn, channels or None, point_mode)
    if step.action == "capture_screenshot":
        return capture_screenshot(instrument, info.idn)
    if step.action == "serial_log":
        duration_s = _float_param(params, "duration_s", 1.0)
        if duration_s < 0:
            raise ValueError("Log-Dauer darf nicht negativ sein.")
        baudrate = _int_param(params, "baudrate", 115200)
        bytesize, parity, stopbits = parse_serial_format(str(params.get("serial_format", "8N1")))
        if _is_direct_serial_address(info.address):
            content = read_direct_serial_log(info.address, duration_s, baudrate, bytesize, parity, stopbits, stop_requested)
        else:
            content = instrument.read_serial_log(duration_s, baudrate=baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits, stop_requested=stop_requested)
        return AcquisitionResult(kind="serial log", file_type="txt", content=content)
    if step.action == "picoscope_analog":
        return instrument.capture_analog(
            PicoScopeAnalogConfig(
                channels=_string_param(params, "channels"),
                voltage_range=_string_param(params, "range"),
                samples=_int_param(params, "samples", 10000),
                interval_us=_float_param(params, "interval_us", 1.0),
            ),
            stop_requested=stop_requested,
        )
    if step.action == "picoscope_digital":
        return instrument.capture_digital(
            PicoScopeDigitalConfig(
                channels=_string_param(params, "channels"),
                logic_level_mv=_int_param(params, "logic_level_mv", 1500),
                samples=_int_param(params, "samples", 10000),
                interval_us=_float_param(params, "interval_us", 1.0),
            ),
            stop_requested=stop_requested,
        )
    raise ValueError(f"Unbekannte Aktion: {step.action}")


def _custom_step_result_value(
    step: SequenceStep,
    result: AcquisitionResult,
    device_infos: dict[str, InstrumentInfo],
    step_result_export: StepResultExportCallback | None,
) -> str:
    summary = _acquisition_result_summary(result)
    if step_result_export is None or not step.device:
        return summary
    export_text = step_result_export(step.device, device_infos[step.device], result)
    return f"{summary}; {export_text}"


def _acquisition_result_summary(result: AcquisitionResult) -> str:
    content = result.content
    if isinstance(content, bytes):
        return f"{result.kind}: {len(content)} bytes {result.file_type}"
    text = str(content)
    if result.file_type == "csv":
        return f"{result.kind}: {len(text.splitlines())} Zeilen, {len(text)} Zeichen"
    if result.file_type == "txt":
        return f"{result.kind}: {len(text.splitlines())} Zeilen, {len(text)} Zeichen"
    return f"{result.kind}: {text}"


def _validate_custom_sequence_step(step: SequenceStep) -> None:
    required_params = {
        "generator_set_frequency": {"frequency", "power"},
        "generator_set_power": {"power"},
        "generator_rf": {"enabled"},
        "power_supply_set": {"voltage", "current", "channel"},
        "power_supply_output": {"enabled", "channel"},
        "power_supply_master_output": {"enabled"},
        "dmm_read": set(),
        "scope_measure": {"measurement", "channel"},
        "capture_waveform": set(),
        "capture_screenshot": set(),
        "serial_log": {"duration_s", "baudrate", "serial_format"},
        "parallel_phase": {"duration_s", "interval_s", "tasks"},
        "picoscope_analog": {"channels", "range", "samples", "interval_us"},
        "picoscope_digital": {"channels", "logic_level_mv", "samples", "interval_us"},
        "wait": {"seconds"},
    }
    if step.action not in required_params:
        raise ValueError(f"Unbekannte Aktion: {step.action}")
    missing = [name for name in required_params[step.action] if str(step.params.get(name, "")).strip() == ""]
    if missing:
        raise ValueError(f"Schritt {step.action} benötigt Parameter: {', '.join(sorted(missing))}")


def _sequence_variables_for_run(variables: list[SequenceVariable], run_index: int) -> dict[str, str]:
    return {variable.name: _variable_value_for_run(variable, run_index) for variable in variables}


def _variable_value_for_run(variable: SequenceVariable, run_index: int) -> str:
    if not variable.start.strip():
        return ""
    if variable.unit == "frequency":
        value = parse_frequency_hz(variable.start) + (run_index - 1) * _parse_frequency_step_hz(variable.step or "0 Hz")
        return format_frequency_hz(value)
    if variable.unit == "voltage":
        value = parse_voltage(variable.start) + (run_index - 1) * parse_voltage(variable.step or "0 V")
        return format_decimal_value(value, "V")
    start = float(variable.start.replace(",", "."))
    step = float((variable.step or "0").replace(",", "."))
    value = start + (run_index - 1) * step
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _resolve_step_params(params: dict[str, object], variables: dict[str, str]) -> dict[str, object]:
    return {key: _resolve_param_value(value, variables) for key, value in params.items()}


def _resolve_param_value(value: object, variables: dict[str, str]) -> object:
    if isinstance(value, str):
        resolved = value
        for name, variable_value in variables.items():
            resolved = resolved.replace("${" + name + "}", variable_value)
        return resolved
    return value


def _custom_sequence_cleanup(
    config: CustomSequenceConfig,
    instruments: dict[str, object],
    device_infos: dict[str, InstrumentInfo],
    started: float,
    stop_requested: StopCallback,
) -> tuple[list[list[object]], int]:
    rows: list[list[object]] = []
    errors = 0
    if not (config.end_rf_off or config.end_power_supply_off or stop_requested()):
        return rows, errors
    for device, info in device_infos.items():
        if _device_only_uses_serial_log(device, config):
            continue
        try:
            profile_idn = info.idn
            if config.end_rf_off:
                try:
                    set_signal_generator_rf_output(instruments[device], profile_idn, False)
                    rows.append(_custom_cleanup_row(started, info, device, "generator_rf", "FINAL_RF_OFF"))
                    continue
                except NotImplementedError:
                    pass
            if config.end_power_supply_off:
                channels = _power_supply_channels_used_by_device(config, device)
                try:
                    if channels:
                        for channel in channels:
                            set_power_supply_output(instruments[device], profile_idn, channel, False)
                            rows.append(_custom_cleanup_row(started, info, device, "power_supply_output", f"FINAL_CHANNEL_{channel}_OFF"))
                    else:
                        set_power_supply_master_output(instruments[device], profile_idn, False, 1)
                        rows.append(_custom_cleanup_row(started, info, device, "power_supply_master_output", "FINAL_OUTPUT_OFF"))
                except NotImplementedError:
                    pass
        except Exception as exc:
            errors += 1
            rows.append(_custom_cleanup_row(started, info, device, "cleanup", f"FINAL_OFF_ERROR: {exc}"))
    return rows, errors


def _power_supply_channels_used_by_device(config: CustomSequenceConfig, device: str) -> list[int]:
    channels: list[int] = []
    for step in config.steps:
        if step.device != device or step.action not in {"power_supply_set", "power_supply_output"}:
            continue
        try:
            channel = _int_param(step.params, "channel", 1)
        except ValueError:
            continue
        if channel not in channels:
            channels.append(channel)
    return channels


def _custom_cleanup_row(started: float, info: InstrumentInfo, device: str, action: str, status: str) -> list[object]:
    return ["", "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{monotonic() - started:.3f}", device, info.address, info.idn, action, "", "", status]


def _format_params(params: dict[str, object]) -> str:
    return "; ".join(f"{key}={value}" for key, value in params.items())


def _string_param(params: dict[str, object], name: str) -> str:
    value = str(params.get(name, "")).strip()
    if not value:
        raise ValueError(f"Parameter fehlt: {name}")
    return value


def _float_param(params: dict[str, object], name: str, default: float) -> float:
    value = params.get(name, default)
    try:
        return float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"Parameter {name} muss eine Zahl sein.") from exc


def _int_param(params: dict[str, object], name: str, default: int) -> int:
    value = params.get(name, default)
    try:
        return int(str(value))
    except ValueError as exc:
        raise ValueError(f"Parameter {name} muss eine ganze Zahl sein.") from exc


def _bool_param(params: dict[str, object], name: str, default: bool) -> bool:
    value = params.get(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in {"1", "TRUE", "JA", "YES", "ON"}


def parse_serial_format(value: str) -> tuple[int, str, float]:
    compact = value.strip().upper().replace(" ", "").replace("-", "").replace("_", "")
    if len(compact) < 3:
        raise ValueError("Serielles Format muss z. B. 8N1 oder 7E1 sein.")
    try:
        bytesize = int(compact[0])
        parity = compact[1]
        stopbits = float(compact[2:])
    except ValueError as exc:
        raise ValueError("Serielles Format muss z. B. 8N1 oder 7E1 sein.") from exc
    if bytesize not in {5, 6, 7, 8}:
        raise ValueError("Datenbits müssen 5, 6, 7 oder 8 sein.")
    if parity not in {"N", "E", "O", "M", "S"}:
        raise ValueError("Parität muss N, E, O, M oder S sein.")
    if stopbits not in {1.0, 1.5, 2.0}:
        raise ValueError("Stopbits müssen 1, 1.5 oder 2 sein.")
    return bytesize, parity, stopbits


def parse_parallel_tasks(value: str) -> list[ParallelTask]:
    tasks: list[ParallelTask] = []
    for part in value.replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        fields = [field.strip() for field in part.split(":")]
        if len(fields) < 2:
            raise ValueError("Parallel-Aufgabe muss z. B. DMM1:dmm oder Scope1:scope:Vpp:1 sein.")
        device = fields[0]
        action = fields[1].lower()
        if action == "dmm":
            tasks.append(ParallelTask(device=device, action="dmm"))
        elif action == "scope":
            measurement = fields[2] if len(fields) >= 3 and fields[2] else "Vpp"
            channel = int(fields[3]) if len(fields) >= 4 and fields[3] else 1
            tasks.append(ParallelTask(device=device, action="scope", measurement=measurement, channel=channel))
        elif action in {"serial", "log"}:
            baudrate = int(fields[2]) if len(fields) >= 3 and fields[2] else 115200
            serial_format = fields[3] if len(fields) >= 4 and fields[3] else "8N1"
            parse_serial_format(serial_format)
            tasks.append(ParallelTask(device=device, action="serial", baudrate=baudrate, serial_format=serial_format))
        else:
            raise ValueError(f"Unbekannte Parallel-Aufgabe: {action}")
    if not tasks:
        raise ValueError("Parallel-Messphase benötigt mindestens eine Aufgabe.")
    return tasks


def run_parallel_phase(
    instruments: dict[str, object],
    device_infos: dict[str, InstrumentInfo],
    duration_s: float,
    interval_s: float,
    tasks: list[ParallelTask],
    stop_requested: StopCallback,
    step_result_export: StepResultExportCallback | None,
) -> str:
    if duration_s <= 0:
        raise ValueError("Parallel-Dauer muss größer als 0 sein.")
    if interval_s <= 0:
        raise ValueError("Parallel-Intervall muss größer als 0 sein.")
    for task in tasks:
        if task.device not in instruments:
            raise ValueError(f"Unbekanntes Gerät in Parallel-Aufgabe: {task.device}")

    rows: list[list[object]] = [["Index", "Timestamp", "ElapsedSeconds", "Device", "Action", "Value", "Status"]]
    serial_exports: list[str] = []
    started = monotonic()
    measurement_tasks = [task for task in tasks if task.action in {"dmm", "scope"}]
    serial_tasks = [task for task in tasks if task.action == "serial"]

    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as executor:
        futures = [executor.submit(_parallel_serial_task, task, instruments[task.device], device_infos[task.device], duration_s, stop_requested, step_result_export) for task in serial_tasks]
        index = 1
        next_sample = started
        while monotonic() - started < duration_s and not stop_requested():
            wait_s = next_sample - monotonic()
            if wait_s > 0:
                _sleep_interruptible(wait_s, stop_requested)
            if stop_requested() or monotonic() - started > duration_s:
                break
            sample_futures = [executor.submit(_parallel_measurement_task, task, instruments[task.device], device_infos[task.device]) for task in measurement_tasks]
            for future in as_completed(sample_futures):
                task, value, status = future.result()
                rows.append([index, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{monotonic() - started:.3f}", task.device, task.action, value, status])
            index += 1
            next_sample += interval_s
        for future in as_completed(futures):
            serial_exports.append(future.result())

    summary_rows = len(rows) - 1
    result = AcquisitionResult(kind="parallel phase", file_type="csv", content=_csv_rows(rows))
    export_text = ""
    first_task = tasks[0]
    if step_result_export is not None:
        export_text = step_result_export(first_task.device, device_infos[first_task.device], result)
    serial_text = "; ".join(text for text in serial_exports if text)
    parts = [f"parallel phase: {summary_rows} Messwerte"]
    if export_text:
        parts.append(export_text)
    if serial_text:
        parts.append(serial_text)
    return "; ".join(parts)


def _parallel_measurement_task(task: ParallelTask, instrument: object, info: InstrumentInfo) -> tuple[ParallelTask, object, str]:
    try:
        if task.action == "dmm":
            return task, read_value(instrument).content, "OK"
        if task.action == "scope":
            return task, read_scope_measurement(instrument, task.measurement, task.channel, info.idn).content, "OK"
        return task, "", f"ERROR: Unsupported task {task.action}"
    except Exception as exc:
        return task, "", f"ERROR: {exc}"


def _parallel_serial_task(
    task: ParallelTask,
    instrument: object,
    info: InstrumentInfo,
    duration_s: float,
    stop_requested: StopCallback,
    step_result_export: StepResultExportCallback | None,
) -> str:
    bytesize, parity, stopbits = parse_serial_format(task.serial_format)
    if _is_direct_serial_address(info.address):
        content = read_direct_serial_log(info.address, duration_s, task.baudrate, bytesize, parity, stopbits, stop_requested)
    else:
        content = instrument.read_serial_log(duration_s, baudrate=task.baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits, stop_requested=stop_requested)
    if step_result_export is None:
        return f"{task.device}: serial log {len(content)} Zeichen"
    result = AcquisitionResult(kind="serial log", file_type="txt", content=content)
    return f"{task.device}: {step_result_export(task.device, info, result)}"


def read_direct_serial_log(
    port: str,
    duration_s: float,
    baudrate: int,
    bytesize: int = 8,
    parity: str = "N",
    stopbits: float = 1,
    stop_requested: StopCallback | None = None,
) -> str:
    stop_requested = stop_requested or (lambda: False)
    if duration_s < 0:
        raise ValueError("Log-Dauer darf nicht negativ sein.")
    if baudrate <= 0:
        raise ValueError("Baudrate muss größer als 0 sein.")
    if serial is None:
        raise RuntimeError("Direkter COM-Port-Zugriff benötigt pyserial. Bitte Abhängigkeiten neu installieren.")
    chunks: list[bytes] = []
    deadline = monotonic() + duration_s
    with serial.Serial(port=port, baudrate=baudrate, bytesize=bytesize, parity=parity, stopbits=stopbits, timeout=0.2) as serial_port:
        while monotonic() < deadline and not stop_requested():
            data = serial_port.read(serial_port.in_waiting or 1)
            if data:
                chunks.append(data)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _channels_param(value: object) -> list[int]:
    text = str(value).strip()
    if not text:
        return []
    channels: list[int] = []
    for part in text.replace(";", ",").split(","):
        part = part.strip().upper().removeprefix("CH")
        if not part:
            continue
        try:
            channels.append(int(part))
        except ValueError as exc:
            raise ValueError(f"Ungültiger Kanal: {part}") from exc
    return channels


def parse_frequency_hz(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    if not normalized:
        raise ValueError("Frequenz darf nicht leer sein.")
    compact = normalized.replace(" ", "").upper()
    units = (("GHZ", 1_000_000_000.0), ("MHZ", 1_000_000.0), ("KHZ", 1_000.0), ("HZ", 1.0))
    multiplier = 1.0
    for suffix, factor in units:
        if compact.endswith(suffix):
            compact = compact[: -len(suffix)]
            multiplier = factor
            break
    try:
        frequency = float(compact) * multiplier
    except ValueError as exc:
        raise ValueError(f"Ungültige Frequenz: {value}") from exc
    if frequency <= 0:
        raise ValueError("Frequenz muss größer als 0 sein.")
    return frequency


def _parse_frequency_step_hz(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    if not normalized:
        return 0.0
    compact = normalized.replace(" ", "").upper()
    units = (("GHZ", 1_000_000_000.0), ("MHZ", 1_000_000.0), ("KHZ", 1_000.0), ("HZ", 1.0))
    multiplier = 1.0
    for suffix, factor in units:
        if compact.endswith(suffix):
            compact = compact[: -len(suffix)]
            multiplier = factor
            break
    try:
        frequency = float(compact) * multiplier
    except ValueError as exc:
        raise ValueError(f"Ungültige Frequenz-Schrittweite: {value}") from exc
    if frequency < 0:
        raise ValueError("Frequenz-Schrittweite darf nicht negativ sein.")
    return frequency


def parse_dbm(value: str) -> float:
    normalized = value.strip().upper().replace(" ", "")
    for suffix in ("DBM", "DB"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    try:
        return float(normalized.replace(",", "."))
    except ValueError as exc:
        raise ValueError("Pegel muss ein dBm-Wert sein, z. B. -30 dBm.") from exc


def parse_voltage(value: str) -> float:
    return _parse_float_with_suffix(value, ("V",), "Spannung")


def parse_ampere(value: str) -> float:
    return _parse_float_with_suffix(value, ("A",), "Strom")


def format_frequency_hz(frequency_hz: float) -> str:
    return f"{frequency_hz:.6f}".rstrip("0").rstrip(".") + "HZ"


def format_decimal_value(value: float, suffix: str) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") + suffix


def _validate_timed_switch_config(config: TimedSwitchConfig) -> None:
    if config.source_type not in {"generator", "power_supply"}:
        raise ValueError(f"Unsupported timed switch source type: {config.source_type}")
    if config.on_s <= 0:
        raise ValueError("ON-Dauer muss größer als 0 sein.")
    if config.off_s < 0:
        raise ValueError("OFF-Dauer darf nicht negativ sein.")
    if config.repetitions <= 0:
        raise ValueError("Wiederholungen müssen größer als 0 sein.")
    if config.source_type == "generator" and parse_dbm(config.generator_power) > config.generator_max_power_dbm:
        raise ValueError(f"Pegel überschreitet Max. Pegel {config.generator_max_power_dbm:g} dBm.")
    if config.source_type == "power_supply":
        voltage = parse_voltage(config.power_supply_voltage)
        current = parse_ampere(config.power_supply_current)
        if voltage > config.power_supply_max_voltage:
            raise ValueError(f"Spannung {voltage:g} V überschreitet Max. V {config.power_supply_max_voltage:g} V.")
        if current > config.power_supply_max_current:
            raise ValueError(f"Strom {current:g} A überschreitet Max. A {config.power_supply_max_current:g} A.")


def _setup_switch_source(source: VisaInstrument, idn: str, config: TimedSwitchConfig) -> None:
    if config.source_type == "generator":
        set_signal_generator(source, idn, config.generator_frequency, config.generator_power, False, config.generator_max_power_dbm, True)
        return
    set_power_supply(
        source,
        idn,
        config.power_supply_channel,
        config.power_supply_voltage,
        config.power_supply_current,
        False,
        config.power_supply_max_voltage,
        config.power_supply_max_current,
    )


def _validate_current_switch_source(source: VisaInstrument, idn: str, config: TimedSwitchConfig) -> None:
    if config.source_type == "generator":
        settings = read_signal_generator_settings(source, idn)
        power_dbm = parse_dbm(settings.power)
        if power_dbm > config.generator_max_power_dbm:
            raise ValueError(f"Aktueller Generatorpegel {power_dbm:g} dBm überschreitet Max. Pegel {config.generator_max_power_dbm:g} dBm.")
        return
    settings = read_power_supply_settings(source, idn, config.power_supply_channel)
    voltage = parse_voltage(settings.voltage_set)
    current = parse_ampere(settings.current_set)
    if voltage > config.power_supply_max_voltage:
        raise ValueError(f"Aktuelle Netzteilspannung {voltage:g} V überschreitet Max. V {config.power_supply_max_voltage:g} V.")
    if current > config.power_supply_max_current:
        raise ValueError(f"Aktuelles Netzteilstromlimit {current:g} A überschreitet Max. A {config.power_supply_max_current:g} A.")


def _switch_source(source: VisaInstrument, idn: str, config: TimedSwitchConfig, enabled: bool) -> None:
    if config.source_type == "generator":
        set_signal_generator_rf_output(source, idn, enabled)
    elif config.power_supply_switch_mode == "channel":
        set_power_supply_output(source, idn, config.power_supply_channel, enabled)
    else:
        set_power_supply_master_output(source, idn, enabled, config.power_supply_channel)


def _frequency_cleanup_row(started: float, generator_info: InstrumentInfo, measurement_info: InstrumentInfo, config: FrequencySweepConfig, status: str) -> list[object]:
    return [
        "",
        "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"{monotonic() - started:.3f}",
        generator_info.address,
        generator_info.idn,
        measurement_info.address,
        measurement_info.idn,
        config.power,
        config.measurement_mode.upper(),
        "RF OFF",
        "",
        "",
        status,
    ]


def _voltage_cleanup_row(started: float, power_supply_info: InstrumentInfo, measurement_info: InstrumentInfo, config: VoltageSweepConfig, status: str) -> list[object]:
    return [
        "",
        "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"{monotonic() - started:.3f}",
        power_supply_info.address,
        power_supply_info.idn,
        measurement_info.address,
        measurement_info.idn,
        config.channel,
        config.current_limit,
        "",
        "",
        config.measurement_mode.upper(),
        "OUTPUT OFF",
        "",
        "",
        status,
    ]


def _switch_row(index: int, started: float, source_info: InstrumentInfo, source_type: str, state: str, duration_s: float, status: str) -> list[object]:
    return [
        index,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"{monotonic() - started:.3f}",
        source_type,
        source_info.address,
        source_info.idn,
        state,
        f"{duration_s:.3f}",
        status,
    ]


def _data_row_count(rows: list[list[object]]) -> int:
    return sum(1 for row in rows[1:] if row and row[0] not in {"", 0, "Summary"})


def _parse_float_with_suffix(value: str, suffixes: tuple[str, ...], label: str) -> float:
    normalized = value.strip().upper().replace(" ", "").replace(",", ".")
    if not normalized:
        raise ValueError(f"{label} darf nicht leer sein.")
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise ValueError(f"Ungültige {label}: {value}") from exc
    if parsed < 0:
        raise ValueError(f"{label} darf nicht negativ sein.")
    return parsed


def _sleep_interruptible(duration_s: float, stop_requested: StopCallback) -> None:
    deadline = monotonic() + duration_s
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0 or stop_requested():
            return
        sleep(min(0.1, remaining))


def _csv_rows(rows: list[list[object]]) -> str:
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue()
