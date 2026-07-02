from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import monotonic, sleep
from typing import Callable

from .acquisition import read_scope_measurement, read_value, set_signal_generator, set_signal_generator_rf_output
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
            except Exception as exc:
                progress(f"RF-Aus am Ende fehlgeschlagen: {exc}")

    actual_count = len(rows) - 1

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


def format_frequency_hz(frequency_hz: float) -> str:
    return f"{frequency_hz:.6f}".rstrip("0").rstrip(".") + "HZ"


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
