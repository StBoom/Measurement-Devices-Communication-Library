from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any

import pyvisa


@dataclass
class InstrumentInfo:
    address: str
    idn: str


class VisaInstrument:
    def __init__(self, address: str, timeout_ms: int = 10000) -> None:
        self.address = address
        self.timeout_ms = timeout_ms
        self._resource_manager: pyvisa.ResourceManager | None = None
        self._instrument: Any | None = None

    def __enter__(self) -> "VisaInstrument":
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def open(self) -> None:
        resource_manager = pyvisa.ResourceManager()
        try:
            instrument = resource_manager.open_resource(self.address)
            instrument.timeout = self.timeout_ms
            instrument.write_termination = "\n"
            instrument.read_termination = "\n"
            if _is_asrl_address(self.address):
                _configure_default_serial(instrument)
            self._resource_manager = resource_manager
            self._instrument = instrument
            if self.address.startswith(("ASRL", "USB")):
                sleep(2.5)
        except Exception:
            try:
                resource_manager.close()
            finally:
                self._resource_manager = None
                self._instrument = None
            raise

    def close(self) -> None:
        instrument = self._instrument
        resource_manager = self._resource_manager
        self._instrument = None
        self._resource_manager = None
        instrument_error: Exception | None = None
        if instrument is not None:
            try:
                instrument.close()
            except Exception as exc:
                instrument_error = exc
        if resource_manager is not None:
            resource_manager.close()
        if instrument_error is not None:
            raise instrument_error

    def write(self, command: str) -> None:
        self._require_open().write(command)

    def query(self, command: str) -> str:
        return str(self._require_open().query(command))

    def configure_serial(self, baudrate: int | None = None, bytesize: int | None = None, parity: str | None = None, stopbits: float | None = None) -> None:
        instrument = self._require_open()
        if baudrate is not None and hasattr(instrument, "baud_rate"):
            instrument.baud_rate = int(baudrate)
        if bytesize is not None and hasattr(instrument, "data_bits"):
            instrument.data_bits = int(bytesize)
        if parity is not None and hasattr(instrument, "parity"):
            instrument.parity = _pyvisa_parity(parity)
        if stopbits is not None and hasattr(instrument, "stop_bits"):
            instrument.stop_bits = _pyvisa_stop_bits(stopbits)

    def configure_termination(self, write_termination: str | None = None, read_termination: str | None = None) -> None:
        instrument = self._require_open()
        if write_termination is not None:
            instrument.write_termination = write_termination
        if read_termination is not None:
            instrument.read_termination = read_termination

    def query_binary(self, command: str) -> bytes:
        instrument = self._require_open()
        original_termination = instrument.read_termination
        instrument.read_termination = None
        try:
            return bytes(instrument.query_binary_values(command, datatype="B", container=bytes))
        finally:
            instrument.read_termination = original_termination

    def read_raw_after_write(self, command: str, delay_s: float = 0.0) -> bytes:
        instrument = self._require_open()
        original_termination = instrument.read_termination
        instrument.read_termination = None
        try:
            instrument.write(command)
            if delay_s:
                sleep(delay_s)
            return bytes(instrument.read_raw())
        finally:
            instrument.read_termination = original_termination

    def read_serial_log(
        self,
        duration_s: float,
        chunk_timeout_ms: int = 200,
        baudrate: int | None = None,
        bytesize: int | None = None,
        parity: str | None = None,
        stopbits: float | None = None,
        stop_requested=None,
    ) -> str:
        instrument = self._require_open()
        if duration_s < 0:
            raise ValueError("Log-Dauer darf nicht negativ sein.")
        if baudrate is not None and baudrate <= 0:
            raise ValueError("Baudrate muss größer als 0 sein.")
        stop_requested = stop_requested or (lambda: False)
        original_timeout = instrument.timeout
        original_read_termination = instrument.read_termination
        original_baud_rate = getattr(instrument, "baud_rate", None)
        original_data_bits = getattr(instrument, "data_bits", None)
        original_parity = getattr(instrument, "parity", None)
        original_stop_bits = getattr(instrument, "stop_bits", None)
        instrument.timeout = max(1, int(chunk_timeout_ms))
        instrument.read_termination = None
        if baudrate is not None and hasattr(instrument, "baud_rate"):
            instrument.baud_rate = int(baudrate)
        if bytesize is not None and hasattr(instrument, "data_bits"):
            instrument.data_bits = int(bytesize)
        if parity is not None and hasattr(instrument, "parity"):
            instrument.parity = _pyvisa_parity(parity)
        if stopbits is not None and hasattr(instrument, "stop_bits"):
            instrument.stop_bits = _pyvisa_stop_bits(stopbits)
        deadline = monotonic() + duration_s
        chunks: list[bytes] = []
        try:
            while monotonic() < deadline and not stop_requested():
                buffered = _bytes_in_buffer(instrument)
                if buffered > 0 and hasattr(instrument, "read_bytes"):
                    chunks.append(bytes(instrument.read_bytes(buffered, break_on_termchar=False)))
                    continue
                if buffered == 0:
                    sleep(min(0.05, max(0.0, deadline - monotonic())))
                    continue
                try:
                    data = bytes(instrument.read_raw())
                except pyvisa.errors.VisaIOError as exc:
                    if getattr(exc, "error_code", None) == pyvisa.constants.StatusCode.error_timeout:
                        continue
                    raise
                if data:
                    chunks.append(data)
            return b"".join(chunks).decode("utf-8", errors="replace")
        finally:
            instrument.timeout = original_timeout
            instrument.read_termination = original_read_termination
            if baudrate is not None and original_baud_rate is not None and hasattr(instrument, "baud_rate"):
                instrument.baud_rate = original_baud_rate
            if bytesize is not None and original_data_bits is not None and hasattr(instrument, "data_bits"):
                instrument.data_bits = original_data_bits
            if parity is not None and original_parity is not None and hasattr(instrument, "parity"):
                instrument.parity = original_parity
            if stopbits is not None and original_stop_bits is not None and hasattr(instrument, "stop_bits"):
                instrument.stop_bits = original_stop_bits

    def send_serial_command(
        self,
        command: str,
        response_duration_s: float = 0.0,
        baudrate: int | None = None,
        bytesize: int | None = None,
        parity: str | None = None,
        stopbits: float | None = None,
        stop_requested=None,
    ) -> str:
        instrument = self._require_open()
        if response_duration_s < 0:
            raise ValueError("Antwort-Lesezeit darf nicht negativ sein.")
        if baudrate is not None and baudrate <= 0:
            raise ValueError("Baudrate muss größer als 0 sein.")
        stop_requested = stop_requested or (lambda: False)
        original_timeout = instrument.timeout
        original_read_termination = instrument.read_termination
        original_baud_rate = getattr(instrument, "baud_rate", None)
        original_data_bits = getattr(instrument, "data_bits", None)
        original_parity = getattr(instrument, "parity", None)
        original_stop_bits = getattr(instrument, "stop_bits", None)
        instrument.timeout = 200
        instrument.read_termination = None
        if baudrate is not None and hasattr(instrument, "baud_rate"):
            instrument.baud_rate = int(baudrate)
        if bytesize is not None and hasattr(instrument, "data_bits"):
            instrument.data_bits = int(bytesize)
        if parity is not None and hasattr(instrument, "parity"):
            instrument.parity = _pyvisa_parity(parity)
        if stopbits is not None and hasattr(instrument, "stop_bits"):
            instrument.stop_bits = _pyvisa_stop_bits(stopbits)
        chunks: list[bytes] = []
        try:
            if hasattr(instrument, "write_raw"):
                instrument.write_raw(_decode_serial_command_text(command))
            else:
                instrument.write(_decode_serial_command_text(command).decode("utf-8", errors="replace"))
            deadline = monotonic() + response_duration_s
            while monotonic() < deadline and not stop_requested():
                buffered = _bytes_in_buffer(instrument)
                if buffered > 0 and hasattr(instrument, "read_bytes"):
                    chunks.append(bytes(instrument.read_bytes(buffered, break_on_termchar=False)))
                    continue
                if buffered == 0:
                    sleep(min(0.05, max(0.0, deadline - monotonic())))
                    continue
                try:
                    data = bytes(instrument.read_raw())
                except pyvisa.errors.VisaIOError as exc:
                    if getattr(exc, "error_code", None) == pyvisa.constants.StatusCode.error_timeout:
                        continue
                    raise
                if data:
                    chunks.append(data)
            return b"".join(chunks).decode("utf-8", errors="replace")
        finally:
            instrument.timeout = original_timeout
            instrument.read_termination = original_read_termination
            if baudrate is not None and original_baud_rate is not None and hasattr(instrument, "baud_rate"):
                instrument.baud_rate = original_baud_rate
            if bytesize is not None and original_data_bits is not None and hasattr(instrument, "data_bits"):
                instrument.data_bits = original_data_bits
            if parity is not None and original_parity is not None and hasattr(instrument, "parity"):
                instrument.parity = original_parity
            if stopbits is not None and original_stop_bits is not None and hasattr(instrument, "stop_bits"):
                instrument.stop_bits = original_stop_bits

    def info(self) -> InstrumentInfo:
        if _is_asrl_address(self.address):
            return InstrumentInfo(address=self.address, idn=self._query_serial_idn().strip())
        return InstrumentInfo(address=self.address, idn=self.query("*IDN?").strip())

    def system_error(self) -> str:
        return self.query(":SYST:ERR?").strip()

    def _require_open(self) -> Any:
        if self._instrument is None:
            raise RuntimeError("VISA instrument is not open")
        return self._instrument

    def _query_serial_idn(self) -> str:
        instrument = self._require_open()
        original_timeout = instrument.timeout
        original_write_termination = instrument.write_termination
        original_read_termination = instrument.read_termination
        last_timeout: pyvisa.errors.VisaIOError | None = None
        attempts = (("\n", "\n"), ("\r\n", "\n"), ("\r", "\n"), ("\r\n", "\r\n"), ("\r", "\r"))
        try:
            instrument.timeout = max(1000, min(int(original_timeout), 3000))
            for write_termination, read_termination in attempts:
                instrument.write_termination = write_termination
                instrument.read_termination = read_termination
                try:
                    if hasattr(instrument, "clear"):
                        instrument.clear()
                except pyvisa.errors.VisaIOError:
                    pass
                try:
                    response = str(instrument.query("*IDN?"))
                except pyvisa.errors.VisaIOError as exc:
                    if getattr(exc, "error_code", None) == pyvisa.constants.StatusCode.error_timeout:
                        last_timeout = exc
                        continue
                    raise
                if response.strip():
                    return response
        finally:
            instrument.timeout = original_timeout
            instrument.write_termination = original_write_termination
            instrument.read_termination = original_read_termination
        if last_timeout is not None:
            raise last_timeout
        return self.query("*IDN?")


def list_resources() -> list[str]:
    resource_manager = pyvisa.ResourceManager()
    try:
        return list(resource_manager.list_resources())
    finally:
        resource_manager.close()


def _is_asrl_address(address: str) -> bool:
    return address.strip().upper().startswith("ASRL")


def _configure_default_serial(instrument: Any) -> None:
    if hasattr(instrument, "baud_rate"):
        instrument.baud_rate = 9600
    if hasattr(instrument, "data_bits"):
        instrument.data_bits = 8
    if hasattr(instrument, "parity"):
        instrument.parity = pyvisa.constants.Parity.none
    if hasattr(instrument, "stop_bits"):
        instrument.stop_bits = pyvisa.constants.StopBits.one


def _bytes_in_buffer(instrument: Any) -> int:
    try:
        value = getattr(instrument, "bytes_in_buffer")
    except Exception:
        return -1
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return -1


def _decode_serial_command_text(command: str) -> bytes:
    text = command.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")
    return text.encode("utf-8")


def _pyvisa_parity(value: str):
    name = {"N": "none", "O": "odd", "E": "even", "M": "mark", "S": "space"}[value.strip().upper()]
    return getattr(pyvisa.constants.Parity, name)


def _pyvisa_stop_bits(value: float):
    if value == 1:
        return pyvisa.constants.StopBits.one
    if value == 1.5:
        return pyvisa.constants.StopBits.one_and_a_half
    if value == 2:
        return pyvisa.constants.StopBits.two
    raise ValueError("Stopbits müssen 1, 1.5 oder 2 sein.")
