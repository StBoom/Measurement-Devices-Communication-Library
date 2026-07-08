from __future__ import annotations

import argparse
import json
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
from .sequence import CustomSequenceConfig, SequenceStep, SequenceVariable, create_sequence_instrument, parse_json_bool, run_custom_sequence
from .visa_client import VisaInstrument, list_resources


def main() -> int:
    logger = setup_logging()
    parser = argparse.ArgumentParser(description="VISA/SCPI instrument communication with Excel export")
    parser.add_argument(
        "action",
        choices=["list", "idn", "value", "scope-value", "screenshot", "waveform", "sparameters", "generator-read", "generator-set", "generator-rf", "sequence-run"],
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
    parser.add_argument("--sequence-file", type=Path, help="Run a free sequence from a JSON file exported by the GUI")
    args = parser.parse_args()

    if args.action == "list":
        for resource in list_resources():
            print(resource)
        return 0

    if args.action == "sequence-run":
        if args.sequence_file is None:
            raise ValueError("sequence-run requires --sequence-file ablauf.json")
        config = load_config(args.config) if args.config.exists() else None
        output = args.output or (config.output if config is not None else Path("results.xlsx"))
        timeout_ms = config.timeout_ms if config is not None else 10000
        return _run_sequence_file(args.sequence_file, output, timeout_ms, logger)

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


def _run_sequence_file(sequence_file: Path, output: Path, timeout_ms: int, logger) -> int:
    config = _load_sequence_config(sequence_file)
    instruments: dict[str, object] = {}
    try:
        for name, address in config.devices.items():
            instruments[name] = create_sequence_instrument(address, timeout_ms=timeout_ms)
            instruments[name].open()
        result_data = run_custom_sequence(
            instruments,
            config,
            progress=lambda message: print(message),
            step_result_export=lambda _device, info, result: _export_sequence_step_result(output, info, result),
        )
        first_device = next(iter(config.devices))
        result = AcquisitionResult(kind="custom sequence", file_type="csv", content=result_data.csv_content)
        export = append_result(output, config.devices[first_device], result_data.device_infos[first_device].idn, result)
        logger.info(
            "Sequence file exported file=%s workbook=%s sheet=%s steps=%s ok=%s errors=%s",
            sequence_file,
            export.workbook_path,
            export.sheet_name,
            result_data.actual_count,
            result_data.ok_count,
            result_data.error_count,
        )
        print(f"Saved sequence result to {export.workbook_path}")
        if export.sheet_name is not None:
            print(f"Saved data to worksheet {export.sheet_name}")
        print(f"Steps: {result_data.actual_count}, OK: {result_data.ok_count}, Errors: {result_data.error_count}")
        return 1 if result_data.error_count else 0
    finally:
        for instrument in instruments.values():
            instrument.close()


def _load_sequence_config(path: Path) -> CustomSequenceConfig:
    data = _load_sequence_data(path)
    devices = data.get("devices", {})
    steps = data.get("steps", [])
    variables = data.get("variables", [])
    if not isinstance(devices, dict) or not isinstance(steps, list):
        raise ValueError("Sequence file must contain 'devices' object and 'steps' list.")
    parsed_steps: list[SequenceStep] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Sequence file contains an invalid step.")
        params = step.get("params", {})
        if not isinstance(params, dict):
            params = {}
        parsed_steps.append(SequenceStep(device=str(step.get("device", "")), action=str(step.get("action", "")), params=dict(params)))
    parsed_variables: list[SequenceVariable] = []
    if isinstance(variables, list):
        for variable in variables:
            if not isinstance(variable, dict):
                raise ValueError("Sequence file contains an invalid variable.")
            unit = str(variable.get("unit", "number"))
            if unit not in {"frequency", "voltage", "number"}:
                unit = "number"
            parsed_variables.append(
                SequenceVariable(
                    name=str(variable.get("name", "")),
                    start=str(variable.get("start", "")),
                    step=str(variable.get("step", "")),
                    unit=unit,  # type: ignore[arg-type]
                )
            )
    return CustomSequenceConfig(
        devices={str(name): str(address) for name, address in devices.items()},
        steps=parsed_steps,
        repeat=int(data.get("repeat", 1)),
        pause_s=float(str(data.get("pause_s", 0)).replace(",", ".")),
        variables=parsed_variables,
        end_rf_off=parse_json_bool(data.get("end_rf_off"), True),
        end_power_supply_off=parse_json_bool(data.get("end_power_supply_off"), False),
        power_supply_max_voltage=float(str(data.get("power_supply_max_voltage", 32.0)).replace(",", ".")),
        power_supply_max_current=float(str(data.get("power_supply_max_current", 10.0)).replace(",", ".")),
    )


def _export_sequence_step_result(output: Path, info, result: AcquisitionResult) -> str:
    export = append_result(output, info.address, info.idn, result)
    if export.artifact_path is not None:
        return f"File: {export.artifact_path}"
    if export.sheet_name is not None:
        return f"Worksheet: {export.sheet_name}"
    return f"Export: {export.workbook_path}"


def _load_sequence_data(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Sequence file not found: {path}")
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Sequence file must contain an object at the top level.")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
