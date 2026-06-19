from __future__ import annotations

from dataclasses import dataclass
from time import sleep
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
        self._resource_manager = pyvisa.ResourceManager()
        self._instrument = self._resource_manager.open_resource(self.address)
        self._instrument.timeout = self.timeout_ms
        self._instrument.write_termination = "\n"
        self._instrument.read_termination = "\n"
        if self.address.startswith(("ASRL", "USB")):
            sleep(2.5)

    def close(self) -> None:
        if self._instrument is not None:
            self._instrument.close()
            self._instrument = None
        if self._resource_manager is not None:
            self._resource_manager.close()
            self._resource_manager = None

    def write(self, command: str) -> None:
        self._require_open().write(command)

    def query(self, command: str) -> str:
        return str(self._require_open().query(command))

    def query_binary(self, command: str) -> bytes:
        instrument = self._require_open()
        original_termination = instrument.read_termination
        instrument.read_termination = None
        try:
            return bytes(instrument.query_binary_values(command, datatype="B", container=bytes))
        finally:
            instrument.read_termination = original_termination

    def info(self) -> InstrumentInfo:
        return InstrumentInfo(address=self.address, idn=self.query("*IDN?").strip())

    def system_error(self) -> str:
        return self.query(":SYST:ERR?").strip()

    def _require_open(self) -> Any:
        if self._instrument is None:
            raise RuntimeError("VISA instrument is not open")
        return self._instrument


def list_resources() -> list[str]:
    resource_manager = pyvisa.ResourceManager()
    try:
        return list(resource_manager.list_resources())
    finally:
        resource_manager.close()
