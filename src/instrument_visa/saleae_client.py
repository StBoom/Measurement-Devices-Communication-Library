from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import sleep
from uuid import uuid4

from .acquisition import AcquisitionResult
from .visa_client import InstrumentInfo


@dataclass(frozen=True)
class SaleaeCaptureConfig:
    digital_channels: str
    duration_s: float
    sample_rate: int
    threshold_v: float = 3.3
    device_id: str = ""


@dataclass(frozen=True)
class SaleaeUartConfig:
    channel: int
    baudrate: int
    duration_s: float
    sample_rate: int
    threshold_v: float = 3.3
    device_id: str = ""


@dataclass(frozen=True)
class SaleaeI2cConfig:
    sda_channel: int
    scl_channel: int
    duration_s: float
    sample_rate: int
    threshold_v: float = 3.3
    device_id: str = ""


@dataclass(frozen=True)
class SaleaeSpiConfig:
    mosi_channel: int
    miso_channel: int
    clock_channel: int
    enable_channel: int
    duration_s: float
    sample_rate: int
    threshold_v: float = 3.3
    device_id: str = ""


@dataclass(frozen=True)
class SaleaeCanConfig:
    channel: int
    bitrate: int
    duration_s: float
    sample_rate: int
    threshold_v: float = 3.3
    device_id: str = ""


class SaleaeInstrument:
    def __init__(self, address: str = "SALEAE::LOCAL", timeout_ms: int = 10000) -> None:
        self.address = address
        self.timeout_ms = timeout_ms

    def open(self) -> None:
        return

    def close(self) -> None:
        return

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def info(self) -> InstrumentInfo:
        return InstrumentInfo(address=self.address, idn="Saleae Logic 2 Automation")

    def capture_saleae_digital(self, config: SaleaeCaptureConfig, output_dir: Path, stop_requested=None) -> AcquisitionResult:
        stop_requested = stop_requested or (lambda: False)
        channels = parse_saleae_channels(config.digital_channels)
        output_dir.mkdir(parents=True, exist_ok=True)
        capture_dir = output_dir / f"saleae-capture-{uuid4().hex[:8]}"
        capture_dir.mkdir(parents=True, exist_ok=True)
        capture_path = capture_dir / "capture.sal"
        raw_dir = capture_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        with _connect_saleae_manager() as manager:
            automation = _saleae_automation()
            device_config = automation.LogicDeviceConfiguration(
                enabled_digital_channels=channels,
                digital_sample_rate=int(config.sample_rate),
                digital_threshold_volts=float(config.threshold_v),
            )
            capture_config = automation.CaptureConfiguration(capture_mode=automation.TimedCaptureMode(duration_seconds=float(config.duration_s)))
            kwargs = {"device_configuration": device_config, "capture_configuration": capture_config}
            if config.device_id.strip():
                kwargs["device_id"] = config.device_id.strip()
            with manager.start_capture(**kwargs) as capture:
                _wait_saleae_capture(capture, config.duration_s, stop_requested)
                capture.export_raw_data_csv(directory=str(raw_dir), digital_channels=channels)
                capture.save_capture(filepath=str(capture_path))
        return AcquisitionResult(kind="saleae capture", file_type="txt", content=f"Capture: {capture_path}\nRaw CSV: {raw_dir}")

    def capture_uart(self, config: SaleaeUartConfig, output_dir: Path, stop_requested=None) -> AcquisitionResult:
        stop_requested = stop_requested or (lambda: False)
        output_dir.mkdir(parents=True, exist_ok=True)
        capture_dir = output_dir / f"saleae-uart-{uuid4().hex[:8]}"
        capture_dir.mkdir(parents=True, exist_ok=True)
        capture_path = capture_dir / "capture.sal"
        uart_path = capture_dir / "uart.csv"

        with _connect_saleae_manager() as manager:
            automation = _saleae_automation()
            device_config = automation.LogicDeviceConfiguration(
                enabled_digital_channels=[int(config.channel)],
                digital_sample_rate=int(config.sample_rate),
                digital_threshold_volts=float(config.threshold_v),
            )
            capture_config = automation.CaptureConfiguration(capture_mode=automation.TimedCaptureMode(duration_seconds=float(config.duration_s)))
            kwargs = {"device_configuration": device_config, "capture_configuration": capture_config}
            if config.device_id.strip():
                kwargs["device_id"] = config.device_id.strip()
            with manager.start_capture(**kwargs) as capture:
                _wait_saleae_capture(capture, config.duration_s, stop_requested)
                analyzer = capture.add_analyzer(
                    "Async Serial",
                    label="UART",
                    settings={
                        "Input Channel": int(config.channel),
                        "Bit Rate (Bits/s)": int(config.baudrate),
                        "Bits per Frame": "8 Bits per Transfer (Standard)",
                        "Stop Bits": "1 Stop Bit (Standard)",
                        "Parity Bit": "No Parity Bit (Standard)",
                        "Significant Bit": "Least Significant Bit Sent First (Standard)",
                        "Signal inversion": "Non Inverted (Standard)",
                        "Mode": "Normal",
                    },
                )
                capture.export_data_table(filepath=str(uart_path), analyzers=[analyzer])
                capture.save_capture(filepath=str(capture_path))
        return AcquisitionResult(kind="saleae uart", file_type="txt", content=f"Capture: {capture_path}\nUART CSV: {uart_path}")

    def capture_i2c(self, config: SaleaeI2cConfig, output_dir: Path, stop_requested=None) -> AcquisitionResult:
        channels = _unique_channels([config.sda_channel, config.scl_channel])
        settings = {"SDA": int(config.sda_channel), "SCL": int(config.scl_channel)}
        return _capture_with_analyzer(self, "i2c", "I2C", "I2C", channels, config.duration_s, config.sample_rate, config.threshold_v, settings, output_dir, stop_requested, config.device_id)

    def capture_spi(self, config: SaleaeSpiConfig, output_dir: Path, stop_requested=None) -> AcquisitionResult:
        channels = _unique_channels([config.mosi_channel, config.miso_channel, config.clock_channel, config.enable_channel])
        settings = {
            "MOSI": int(config.mosi_channel),
            "MISO": int(config.miso_channel),
            "Clock": int(config.clock_channel),
            "Bits per Transfer": "8 Bits per Transfer (Standard)",
            "Clock State": "Clock is Low when inactive (CPOL = 0)",
            "Clock Phase": "Data is Valid on Clock Leading Edge (CPHA = 0)",
            "Significant Bit": "Most Significant Bit Sent First (Standard)",
        }
        if config.enable_channel >= 0:
            settings["Enable"] = int(config.enable_channel)
            settings["Enable Line"] = "Enable line is Active Low (Standard)"
        return _capture_with_analyzer(self, "spi", "SPI", "SPI", channels, config.duration_s, config.sample_rate, config.threshold_v, settings, output_dir, stop_requested, config.device_id)

    def capture_can(self, config: SaleaeCanConfig, output_dir: Path, stop_requested=None) -> AcquisitionResult:
        settings = {"Input Channel": int(config.channel), "Bit Rate (Bits/s)": int(config.bitrate)}
        return _capture_with_analyzer(self, "can", "CAN", "CAN", [int(config.channel)], config.duration_s, config.sample_rate, config.threshold_v, settings, output_dir, stop_requested, config.device_id)


def is_saleae_address(address: str) -> bool:
    return address.strip().upper().startswith("SALEAE::")


def create_saleae_instrument(address: str, timeout_ms: int = 10000) -> SaleaeInstrument:
    if not is_saleae_address(address):
        raise ValueError(f"Unsupported Saleae address: {address}")
    return SaleaeInstrument(address, timeout_ms)


def list_saleae_resources() -> list[str]:
    try:
        with _connect_saleae_manager() as manager:
            devices = manager.get_devices(include_simulation_devices=False)
    except Exception:
        return []
    return ["SALEAE::LOCAL"] if devices else []


def parse_saleae_channels(value: str) -> list[int]:
    channels: list[int] = []
    for part in value.upper().replace("D", "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError("Saleae-Kanalbereich ist rückwärts angegeben.")
            channels.extend(range(start, end + 1))
        else:
            channels.append(int(part))
    unique: list[int] = []
    for channel in channels:
        if channel < 0:
            continue
        if channel < 0 or channel > 15:
            raise ValueError("Saleae-Kanäle müssen zwischen D0 und D15 liegen.")
        if channel not in unique:
            unique.append(channel)
    if not unique:
        raise ValueError("Bitte mindestens einen Saleae-Kanal angeben.")
    return unique


def _unique_channels(channels: list[int]) -> list[int]:
    unique: list[int] = []
    for channel in channels:
        if channel < 0 or channel > 15:
            raise ValueError("Saleae-Kanäle müssen zwischen D0 und D15 liegen.")
        if channel not in unique:
            unique.append(channel)
    return unique


def _capture_with_analyzer(
    instrument: SaleaeInstrument,
    folder_prefix: str,
    kind_suffix: str,
    analyzer_name: str,
    channels: list[int],
    duration_s: float,
    sample_rate: int,
    threshold_v: float,
    analyzer_settings: dict[str, object],
    output_dir: Path,
    stop_requested,
    device_id: str = "",
) -> AcquisitionResult:
    stop_requested = stop_requested or (lambda: False)
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_dir = output_dir / f"saleae-{folder_prefix}-{uuid4().hex[:8]}"
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_path = capture_dir / "capture.sal"
    export_path = capture_dir / f"{folder_prefix}.csv"

    with _connect_saleae_manager() as manager:
        automation = _saleae_automation()
        device_config = automation.LogicDeviceConfiguration(
            enabled_digital_channels=channels,
            digital_sample_rate=int(sample_rate),
            digital_threshold_volts=float(threshold_v),
        )
        capture_config = automation.CaptureConfiguration(capture_mode=automation.TimedCaptureMode(duration_seconds=float(duration_s)))
        kwargs = {"device_configuration": device_config, "capture_configuration": capture_config}
        if device_id.strip():
            kwargs["device_id"] = device_id.strip()
        with manager.start_capture(**kwargs) as capture:
            _wait_saleae_capture(capture, duration_s, stop_requested)
            analyzer = capture.add_analyzer(analyzer_name, label=kind_suffix, settings=analyzer_settings)
            capture.export_data_table(filepath=str(export_path), analyzers=[analyzer])
            capture.save_capture(filepath=str(capture_path))
    return AcquisitionResult(kind=f"saleae {kind_suffix.lower()}", file_type="txt", content=f"Capture: {capture_path}\n{kind_suffix} CSV: {export_path}")


def _saleae_automation():
    try:
        from saleae import automation
    except ImportError as exc:
        raise RuntimeError("Saleae Logic 2 Automation benötigt das Paket logic2-automation und eine laufende Logic-2-App mit aktivierter Automation.") from exc
    return automation


def _connect_saleae_manager():
    automation = _saleae_automation()
    return automation.Manager.connect(port=10430, connect_timeout_seconds=5.0)


def _wait_saleae_capture(capture, duration_s: float, stop_requested) -> None:
    if not stop_requested:
        capture.wait()
        return
    elapsed = 0.0
    while elapsed < duration_s:
        if stop_requested():
            capture.stop()
            raise RuntimeError("Saleae-Aufnahme wurde gestoppt.")
        sleep(0.1)
        elapsed += 0.1
    capture.wait()
