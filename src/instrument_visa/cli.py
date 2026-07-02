from __future__ import annotations

import argparse
from pathlib import Path

from .acquisition import (
    AcquisitionResult,
    capture_screenshot,
    capture_sparameters,
    capture_waveform,
    read_scope_measurement,
    read_signal_generator_settings,
    read_value,
    set_signal_generator,
    set_signal_generator_rf_output,
)
from .config import load_config
from .excel_export import append_result
from .logging_utils import setup_logging
from .visa_client import VisaInstrument, list_resources


def main() -> int:
    logger = setup_logging()
    parser = argparse.ArgumentParser(description="VISA/SCPI instrument communication with Excel export")
    parser.add_argument(
        "action",
        choices=["list", "idn", "value", "scope-value", "screenshot", "waveform", "sparameters", "generator-read", "generator-set", "generator-rf"],
    )
    parser.add_argument("--config", type=Path, default=Path("config.ini"))
    parser.add_argument("--address", help="Override VISA address from config")
    parser.add_argument("--output", type=Path, help="Override Excel output path")
    parser.add_argument("--measurement", default="Vpp", choices=["Vpp", "Vrms", "Frequency", "Period", "Vmax", "Vmin"])
    parser.add_argument("--channel", type=int, default=1, choices=[1, 2, 3, 4])
    parser.add_argument("--channels", help="Comma-separated waveform channels, e.g. 1,2,4. Default: displayed channels.")
    parser.add_argument("--point-mode", default="RAW", choices=["RAW", "NORMAL", "MAXIMUM"])
    parser.add_argument("--frequency", help='Signal generator CW frequency, e.g. "100 MHz" or "1GHz"')
    parser.add_argument("--power", help='Signal generator output power, e.g. "-30 dBm"')
    parser.add_argument("--rf", choices=["on", "off"], help="Signal generator RF output state")
    parser.add_argument("--max-power", type=float, default=0.0, help="Signal generator safety limit in dBm. Default: 0 dBm")
    parser.add_argument("--keep-rf-during-change", action="store_true", help="Do not switch RF off before changing frequency/power")
    args = parser.parse_args()

    if args.action == "list":
        for resource in list_resources():
            print(resource)
        return 0

    config = load_config(args.config) if args.config.exists() else None
    if config is None and args.address is None:
        raise FileNotFoundError(f"Config file not found: {args.config}. Use --address or create config.ini.")

    address = args.address or config.address
    timeout_ms = config.timeout_ms if config is not None else 10000
    title = config.title if config is not None else ""
    output = args.output or (config.output if config is not None else Path("results.xlsx"))

    with VisaInstrument(address=address, timeout_ms=timeout_ms) as instrument:
        info = instrument.info()
        logger.info("Action started action=%s address=%s idn=%s", args.action, address, info.idn)
        if args.action == "idn":
            print(info.idn)
            return 0
        if args.action == "value":
            result = read_value(instrument)
        elif args.action == "scope-value":
            result = read_scope_measurement(instrument, args.measurement, args.channel, info.idn)
        elif args.action == "screenshot":
            result = capture_screenshot(instrument, info.idn, title)
        elif args.action == "waveform":
            channels = _parse_channels(args.channels) if args.channels else None
            result = capture_waveform(instrument, info.idn, channels, args.point_mode)
        elif args.action == "sparameters":
            if config is None:
                raise FileNotFoundError("S-parameter export requires config.ini for selected ports and format.")
            result = capture_sparameters(instrument, info.idn, config.sparameters)
        elif args.action == "generator-read":
            settings = read_signal_generator_settings(instrument, info.idn)
            result = _generator_settings_result(settings)
        elif args.action == "generator-set":
            if args.frequency is None or args.power is None or args.rf is None:
                raise ValueError('generator-set requires --frequency, --power and --rf on|off')
            result = set_signal_generator(
                instrument,
                info.idn,
                args.frequency,
                args.power,
                args.rf == "on",
                args.max_power,
                not args.keep_rf_during_change,
            )
        elif args.action == "generator-rf":
            if args.rf is None:
                raise ValueError('generator-rf requires --rf on|off')
            result = set_signal_generator_rf_output(instrument, info.idn, args.rf == "on")
        else:
            raise ValueError(f"Unsupported action: {args.action}")

    export = append_result(output, address, info.idn, result)
    logger.info("Action exported action=%s workbook=%s artifact=%s sheet=%s", args.action, export.workbook_path, export.artifact_path, export.sheet_name)
    print(f"Saved {result.kind} result to {export.workbook_path}")
    if export.artifact_path is not None:
        print(f"Saved artifact to {export.artifact_path}")
    if export.sheet_name is not None:
        print(f"Saved data to worksheet {export.sheet_name}")
    return 0


def _parse_channels(value: str) -> list[int]:
    channels = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not channels or any(channel not in {1, 2, 3, 4} for channel in channels):
        raise ValueError("--channels must contain one or more channels from 1 to 4")
    return channels


def _generator_settings_result(settings) -> AcquisitionResult:
    content = "Setting,Value\n" f"Frequency,{settings.frequency}\n" f"Power,{settings.power}\n" f"RFOutput,{settings.rf_output}"
    return AcquisitionResult(kind="signal_generator", file_type="csv", content=content)


if __name__ == "__main__":
    raise SystemExit(main())
