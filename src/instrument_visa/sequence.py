from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import monotonic, sleep
from typing import Callable

from .acquisition import (
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
from .visa_client import InstrumentInfo, VisaInstrument


MAX_SWEEP_POINTS = 10000
ProgressCallback = Callable[[str], None]
StopCallback = Callable[[], bool]


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
