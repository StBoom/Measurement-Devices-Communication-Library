from __future__ import annotations

import ctypes
from dataclasses import dataclass
from time import monotonic, sleep

from .acquisition import AcquisitionResult
from .visa_client import InstrumentInfo


PS2000A_CHANNELS = {"A": 0, "B": 1, "C": 2, "D": 3}
PS2000A_DIGITAL_PORTS = {"P0": 0x80, "P1": 0x81}
PS2000A_COUPLING = {"DC": 1, "AC": 0}
PS2000A_RATIO_MODE_NONE = 0
PS2000A_TIME_UNITS_NS = 2
PS2000A_TIMEBASE_NS = 8
PS2000A_MAX_READY_WAIT_S = 30.0
PICO_OK = 0

PS2000A_RANGES = {
    "10MV": (0, 0.01),
    "20MV": (1, 0.02),
    "50MV": (2, 0.05),
    "100MV": (3, 0.1),
    "200MV": (4, 0.2),
    "500MV": (5, 0.5),
    "1V": (6, 1.0),
    "2V": (7, 2.0),
    "5V": (8, 5.0),
    "10V": (9, 10.0),
    "20V": (10, 20.0),
    "50V": (11, 50.0),
}


@dataclass(frozen=True)
class PicoScopeAnalogConfig:
    channels: str | list[str]
    voltage_range: str
    samples: int
    interval_us: float
    coupling: str = "DC"


@dataclass(frozen=True)
class PicoScopeDigitalConfig:
    channels: str | list[int]
    logic_level_mv: int
    samples: int
    interval_us: float


class PicoScope2000AInstrument:
    def __init__(self, address: str = "PICO2000A::AUTO", timeout_ms: int = 10000) -> None:
        self.address = address
        self.timeout_ms = timeout_ms
        self._dll = None
        self._handle: int | None = None
        self._max_adc: int = 32767

    def open(self) -> None:
        self._dll = _load_ps2000a()
        handle = ctypes.c_int16()
        serial = _serial_from_address(self.address)
        status = self._dll.ps2000aOpenUnit(ctypes.byref(handle), serial)
        _check_pico_status("ps2000aOpenUnit", status)
        self._handle = int(handle.value)
        try:
            max_adc = ctypes.c_int16()
            status = self._dll.ps2000aMaximumValue(self._handle, ctypes.byref(max_adc))
            _check_pico_status("ps2000aMaximumValue", status)
            self._max_adc = int(max_adc.value)
        except AttributeError:
            self._max_adc = 32767

    def close(self) -> None:
        if self._dll is not None and self._handle is not None:
            self._dll.ps2000aCloseUnit(self._handle)
        self._handle = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def info(self) -> InstrumentInfo:
        return InstrumentInfo(address=self.address, idn="PicoScope 2000A")

    def capture_analog(self, config: PicoScopeAnalogConfig, stop_requested=None) -> AcquisitionResult:
        dll, handle = self._require_open()
        stop_requested = stop_requested or (lambda: False)
        channels = parse_pico_analog_channels(config.channels)
        range_code, full_scale_v = _pico_range(config.voltage_range)
        coupling = PS2000A_COUPLING.get(config.coupling.strip().upper(), PS2000A_COUPLING["DC"])
        samples = _positive_int(config.samples, "Samples")
        timebase = _timebase_from_interval_us(config.interval_us)

        _stop_capture(dll, handle)
        _disable_digital_ports(dll, handle)
        for channel in PS2000A_CHANNELS:
            enabled = channel in channels
            status = dll.ps2000aSetChannel(handle, PS2000A_CHANNELS[channel], int(enabled), coupling, range_code, ctypes.c_float(0.0))
            if enabled:
                _check_pico_status("ps2000aSetChannel", status)

        buffers: dict[str, ctypes.Array] = {}
        for channel in channels:
            buffer = (ctypes.c_int16 * samples)()
            buffers[channel] = buffer
            status = dll.ps2000aSetDataBuffer(handle, PS2000A_CHANNELS[channel], buffer, samples, 0, PS2000A_RATIO_MODE_NONE)
            _check_pico_status("ps2000aSetDataBuffer", status)

        _run_block(dll, handle, samples, timebase, self.timeout_ms / 1000.0, stop_requested)
        captured = ctypes.c_uint32(samples)
        overflow = ctypes.c_int16()
        status = dll.ps2000aGetValues(handle, 0, ctypes.byref(captured), 1, PS2000A_RATIO_MODE_NONE, 0, ctypes.byref(overflow))
        _check_pico_status("ps2000aGetValues", status)

        actual = int(captured.value)
        rows: list[list[object]] = [["Time_s", *(f"{channel}_V" for channel in channels)]]
        interval_s = config.interval_us / 1_000_000.0
        for index in range(actual):
            row: list[object] = [f"{index * interval_s:.9f}"]
            for channel in channels:
                row.append(f"{_adc_to_volts(buffers[channel][index], self._max_adc, full_scale_v):.9g}")
            rows.append(row)
        return AcquisitionResult(kind="picoscope analog", file_type="csv", content=_csv_rows(rows))

    def capture_digital(self, config: PicoScopeDigitalConfig, stop_requested=None) -> AcquisitionResult:
        dll, handle = self._require_open()
        stop_requested = stop_requested or (lambda: False)
        digital_channels = parse_pico_digital_channels(config.channels)
        samples = _positive_int(config.samples, "Samples")
        timebase = _timebase_from_interval_us(config.interval_us)
        ports = sorted({channel // 8 for channel in digital_channels})

        _stop_capture(dll, handle)
        _disable_analog_channels(dll, handle)
        for port in (0, 1):
            port_name = f"P{port}"
            status = dll.ps2000aSetDigitalPort(handle, PS2000A_DIGITAL_PORTS[port_name], int(port in ports), int(config.logic_level_mv))
            if port in ports:
                _check_pico_status("ps2000aSetDigitalPort", status)

        buffers: dict[int, ctypes.Array] = {}
        for port in ports:
            buffer = (ctypes.c_int16 * samples)()
            buffers[port] = buffer
            status = dll.ps2000aSetDataBuffer(handle, PS2000A_DIGITAL_PORTS[f"P{port}"], buffer, samples, 0, PS2000A_RATIO_MODE_NONE)
            _check_pico_status("ps2000aSetDataBuffer", status)

        _run_block(dll, handle, samples, timebase, self.timeout_ms / 1000.0, stop_requested)
        captured = ctypes.c_uint32(samples)
        overflow = ctypes.c_int16()
        status = dll.ps2000aGetValues(handle, 0, ctypes.byref(captured), 1, PS2000A_RATIO_MODE_NONE, 0, ctypes.byref(overflow))
        _check_pico_status("ps2000aGetValues", status)

        actual = int(captured.value)
        rows: list[list[object]] = [["Time_s", *(f"D{channel}" for channel in digital_channels)]]
        interval_s = config.interval_us / 1_000_000.0
        for index in range(actual):
            row: list[object] = [f"{index * interval_s:.9f}"]
            for channel in digital_channels:
                port = channel // 8
                bit = channel % 8
                row.append(1 if int(buffers[port][index]) & (1 << bit) else 0)
            rows.append(row)
        return AcquisitionResult(kind="picoscope digital", file_type="csv", content=_csv_rows(rows))

    def _require_open(self):
        if self._dll is None or self._handle is None:
            raise RuntimeError("PicoScope ist nicht geöffnet.")
        return self._dll, self._handle


def is_picoscope_address(address: str) -> bool:
    normalized = address.strip().upper()
    return normalized.startswith("PICO::") or normalized.startswith("PICO2000A::")


def create_picoscope_instrument(address: str, timeout_ms: int = 10000) -> PicoScope2000AInstrument:
    normalized = address.strip().upper()
    if normalized.startswith("PICO::") or normalized.startswith("PICO2000A::"):
        return PicoScope2000AInstrument(address, timeout_ms)
    raise ValueError(f"Unsupported PicoScope address: {address}")


def list_picoscope_resources() -> list[str]:
    try:
        dll = _load_ps2000a()
    except RuntimeError:
        return []
    count = ctypes.c_int16()
    serial_buffer = ctypes.create_string_buffer(4096)
    serial_length = ctypes.c_int16(len(serial_buffer))
    try:
        status = dll.ps2000aEnumerateUnits(ctypes.byref(count), serial_buffer, ctypes.byref(serial_length))
    except Exception:
        return []
    if int(status) != PICO_OK or count.value <= 0:
        return []
    serials = serial_buffer.value.decode("ascii", errors="ignore").strip()
    if not serials:
        return ["PICO2000A::AUTO"]
    return [f"PICO2000A::SERIAL::{serial.strip()}" for serial in serials.replace(";", ",").split(",") if serial.strip()]


def parse_pico_analog_channels(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip().upper().removeprefix("CH") for part in value.replace(";", ",").split(",")]
    else:
        parts = [str(part).strip().upper().removeprefix("CH") for part in value]
    channels: list[str] = []
    for part in parts:
        if not part:
            continue
        if part not in PS2000A_CHANNELS:
            raise ValueError(f"Ungültiger PicoScope-Analogkanal: {part}")
        if part not in channels:
            channels.append(part)
    if not channels:
        raise ValueError("Bitte mindestens einen PicoScope-Analogkanal auswählen.")
    return channels


def parse_pico_digital_channels(value: str | list[int]) -> list[int]:
    if isinstance(value, str):
        tokens = [part.strip().upper().removeprefix("D") for part in value.replace(";", ",").split(",") if part.strip()]
        channels: list[int] = []
        for token in tokens:
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                start = int(start_text.removeprefix("D"))
                end = int(end_text.removeprefix("D"))
                channels.extend(range(start, end + 1))
            else:
                channels.append(int(token))
    else:
        channels = [int(channel) for channel in value]
    unique: list[int] = []
    for channel in channels:
        if channel < 0 or channel > 15:
            raise ValueError(f"Ungültiger PicoScope-Digitalkanal: D{channel}")
        if channel not in unique:
            unique.append(channel)
    if not unique:
        raise ValueError("Bitte mindestens einen PicoScope-Digitalkanal auswählen.")
    return unique


def _load_ps2000a():
    for name in ("ps2000a.dll", "ps2000a"):
        try:
            return ctypes.WinDLL(name)
        except (AttributeError, OSError):
            try:
                return ctypes.CDLL(name)
            except OSError:
                continue
    raise RuntimeError("PicoSDK 2000A nicht gefunden. Bitte PicoSDK 64-bit installieren.")


def _serial_from_address(address: str):
    normalized = address.strip()
    upper = normalized.upper()
    if "::SERIAL::" not in upper:
        return None
    serial_index = upper.index("::SERIAL::") + len("::SERIAL::")
    serial = normalized[serial_index:].strip()
    return serial.encode("ascii") if serial else None


def _pico_range(value: str) -> tuple[int, float]:
    key = value.strip().upper().replace(" ", "")
    if key not in PS2000A_RANGES:
        raise ValueError(f"Ungültiger PicoScope-Bereich: {value}")
    return PS2000A_RANGES[key]


def _positive_int(value: int, label: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{label} muss größer als 0 sein.")
    return parsed


def _timebase_from_interval_us(interval_us: float) -> int:
    if interval_us <= 0:
        raise ValueError("Intervall muss größer als 0 sein.")
    interval_ns = interval_us * 1000.0
    return max(0, int(round(interval_ns / PS2000A_TIMEBASE_NS)) + 2)


def _run_block(dll, handle: int, samples: int, timebase: int, timeout_s: float, stop_requested) -> None:
    time_indisposed_ms = ctypes.c_int32()
    status = dll.ps2000aRunBlock(handle, 0, samples, timebase, 0, ctypes.byref(time_indisposed_ms), 0, None, None)
    _check_pico_status("ps2000aRunBlock", status)
    ready = ctypes.c_int16(0)
    deadline = monotonic() + max(0.1, min(timeout_s, PS2000A_MAX_READY_WAIT_S))
    while not ready.value:
        if stop_requested():
            _stop_capture(dll, handle)
            raise RuntimeError("PicoScope-Aufnahme wurde gestoppt.")
        status = dll.ps2000aIsReady(handle, ctypes.byref(ready))
        _check_pico_status("ps2000aIsReady", status)
        if monotonic() > deadline:
            raise TimeoutError("PicoScope Block-Aufnahme hat nicht rechtzeitig abgeschlossen.")
        sleep(0.01)


def _stop_capture(dll, handle: int) -> None:
    try:
        dll.ps2000aStop(handle)
    except AttributeError:
        return


def _disable_analog_channels(dll, handle: int) -> None:
    for channel_code in PS2000A_CHANNELS.values():
        try:
            dll.ps2000aSetChannel(handle, channel_code, 0, PS2000A_COUPLING["DC"], PS2000A_RANGES["5V"][0], ctypes.c_float(0.0))
        except Exception:
            pass


def _disable_digital_ports(dll, handle: int) -> None:
    for port_code in PS2000A_DIGITAL_PORTS.values():
        try:
            dll.ps2000aSetDigitalPort(handle, port_code, 0, 1500)
        except Exception:
            pass


def _adc_to_volts(value: int, max_adc: int, full_scale_v: float) -> float:
    return float(value) * full_scale_v / float(max_adc or 32767)


def _check_pico_status(action: str, status: int) -> None:
    if int(status) != PICO_OK:
        raise RuntimeError(f"{action} fehlgeschlagen: PicoStatus {int(status)}")


def _csv_rows(rows: list[list[object]]) -> str:
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue()
