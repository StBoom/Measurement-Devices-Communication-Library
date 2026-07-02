from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from time import sleep

from .config import SParameterConfig
from .profiles import detect_profile, hmp_channel_count
from .visa_client import VisaInstrument


LOGGER = logging.getLogger("instrument_visa")


@dataclass(frozen=True)
class AcquisitionResult:
    kind: str
    file_type: str
    content: str | bytes
    message: str = ""


@dataclass(frozen=True)
class SimpleScreenshotCommand:
    file_type: str
    query: str
    setup: tuple[str, ...] = ()
    cleanup: tuple[str, ...] = ()
    delay_s: float = 0.0


@dataclass(frozen=True)
class SignalGeneratorSettings:
    frequency: str
    power: str
    rf_output: str


@dataclass(frozen=True)
class PowerSupplySettings:
    channel: int
    voltage_set: str
    current_set: str
    voltage_measured: str
    current_measured: str
    output_selected: str
    output_general: str


def read_value(instrument: VisaInstrument) -> AcquisitionResult:
    LOGGER.info("SCPI action=dmm_value command=%s", ":READ?")
    return AcquisitionResult(kind="value", file_type="value", content=instrument.query(":READ?").strip())


def read_power_supply_settings(instrument: VisaInstrument, idn: str, channel: int) -> PowerSupplySettings:
    profile = detect_profile(idn)
    if not profile.supports_power_supply:
        raise NotImplementedError(f"Unsupported power supply device: {idn}")
    _validate_power_supply_channel(channel, idn)
    LOGGER.info("SCPI action=power_supply_read profile=%s channel=%s", profile.key, channel)
    instrument.write(f"INST:NSEL {channel}")
    return PowerSupplySettings(
        channel=channel,
        voltage_set=instrument.query("VOLT?").strip(),
        current_set=instrument.query("CURR?").strip(),
        voltage_measured=instrument.query("MEAS:VOLT?").strip(),
        current_measured=instrument.query("MEAS:CURR?").strip(),
        output_selected=_normalize_rf_state(instrument.query("OUTP:SEL?").strip()),
        output_general=_normalize_rf_state(instrument.query("OUTP:GEN?").strip()),
    )


def set_power_supply(
    instrument: VisaInstrument,
    idn: str,
    channel: int,
    voltage: str,
    current: str,
    output_enabled: bool,
    max_voltage: float = 32.0,
    max_current: float = 10.0,
) -> AcquisitionResult:
    profile = detect_profile(idn)
    if not profile.supports_power_supply:
        raise NotImplementedError(f"Unsupported power supply device: {idn}")
    _validate_power_supply_channel(channel, idn)
    voltage = voltage.strip()
    current = current.strip()
    voltage_value = _parse_float_with_suffix(voltage, ("V",))
    current_value = _parse_float_with_suffix(current, ("A",))
    if voltage_value < 0:
        raise ValueError("Requested voltage must not be negative")
    if current_value < 0:
        raise ValueError("Requested current must not be negative")
    if voltage_value > max_voltage:
        raise ValueError(f"Requested voltage {voltage_value:g} V exceeds max voltage {max_voltage:g} V")
    if current_value > max_current:
        raise ValueError(f"Requested current {current_value:g} A exceeds max current {max_current:g} A")

    LOGGER.info("SCPI action=power_supply_set profile=%s channel=%s voltage=%s current=%s output=%s", profile.key, channel, voltage, current, output_enabled)
    instrument.write(f"INST:NSEL {channel}")
    instrument.write(f"VOLT {voltage}")
    instrument.write(f"CURR {current}")
    instrument.write(f"OUTP:SEL {'1' if output_enabled else '0'}")
    if output_enabled:
        instrument.write("OUTP:GEN 1")
    settings = read_power_supply_settings(instrument, idn, channel)
    return AcquisitionResult(kind="power_supply", file_type="csv", content=_format_power_supply_settings(settings))


def set_power_supply_output(instrument: VisaInstrument, idn: str, channel: int, enabled: bool) -> AcquisitionResult:
    profile = detect_profile(idn)
    if not profile.supports_power_supply:
        raise NotImplementedError(f"Unsupported power supply device: {idn}")
    _validate_power_supply_channel(channel, idn)
    LOGGER.info("SCPI action=power_supply_output profile=%s channel=%s enabled=%s", profile.key, channel, enabled)
    instrument.write(f"INST:NSEL {channel}")
    instrument.write(f"OUTP:SEL {'1' if enabled else '0'}")
    if enabled:
        instrument.write("OUTP:GEN 1")
    settings = read_power_supply_settings(instrument, idn, channel)
    return AcquisitionResult(kind="power_supply", file_type="csv", content=_format_power_supply_settings(settings))


def set_power_supply_master_output(instrument: VisaInstrument, idn: str, enabled: bool, channel: int = 1) -> AcquisitionResult:
    profile = detect_profile(idn)
    if not profile.supports_power_supply:
        raise NotImplementedError(f"Unsupported power supply device: {idn}")
    _validate_power_supply_channel(channel, idn)
    LOGGER.info("SCPI action=power_supply_master_output profile=%s enabled=%s", profile.key, enabled)
    instrument.write(f"OUTP:GEN {'1' if enabled else '0'}")
    settings = read_power_supply_settings(instrument, idn, channel)
    return AcquisitionResult(kind="power_supply", file_type="csv", content=_format_power_supply_settings(settings))


def read_signal_generator_settings(instrument: VisaInstrument, idn: str) -> SignalGeneratorSettings:
    profile = detect_profile(idn)
    if not profile.supports_signal_generator:
        raise NotImplementedError(f"Unsupported signal generator device: {idn}")
    LOGGER.info("SCPI action=signal_generator_read profile=%s", profile.key)
    if profile.key == "rs_smg_legacy":
        frequency = instrument.query("RF?").strip()
        level = instrument.query("LEVEL:RF?").strip()
        return SignalGeneratorSettings(
            frequency=_strip_prefixed_value(frequency, "RF"),
            power=_strip_prefixed_value(level, "LEVEL:RF"),
            rf_output="OFF" if level.upper().startswith("LEVEL:RF:OFF") else "ON",
        )
    return SignalGeneratorSettings(
        frequency=instrument.query(":SOUR:FREQ:CW?").strip(),
        power=instrument.query(":SOUR:POW?").strip(),
        rf_output=_normalize_rf_state(instrument.query(":OUTP?").strip()),
    )


def set_signal_generator(
    instrument: VisaInstrument,
    idn: str,
    frequency: str,
    power: str,
    rf_output: bool,
    max_power_dbm: float = 0.0,
    rf_off_before_change: bool = True,
) -> AcquisitionResult:
    profile = detect_profile(idn)
    if not profile.supports_signal_generator:
        raise NotImplementedError(f"Unsupported signal generator device: {idn}")

    frequency = frequency.strip()
    power = power.strip()
    if not frequency:
        raise ValueError("Frequency must not be empty")
    if not power:
        raise ValueError("Power must not be empty")
    requested_power_dbm = _parse_dbm(power)
    if requested_power_dbm > max_power_dbm:
        raise ValueError(f"Requested power {requested_power_dbm:g} dBm exceeds max power {max_power_dbm:g} dBm")

    LOGGER.info(
        "SCPI action=signal_generator_set profile=%s frequency=%s power=%s rf_output=%s max_power_dbm=%s rf_off_before_change=%s",
        profile.key,
        frequency,
        power,
        rf_output,
        max_power_dbm,
        rf_off_before_change,
    )
    if profile.key == "rs_smg_legacy":
        if rf_off_before_change:
            instrument.write("LEVEL:RF:OFF")
        instrument.write(f"RF {frequency}")
        instrument.write(f"LEVEL:RF {power}")
        instrument.write(f"LEVEL:RF:{'ON' if rf_output else 'OFF'}")
        settings = read_signal_generator_settings(instrument, idn)
        return AcquisitionResult(kind="signal_generator", file_type="csv", content=_format_signal_generator_settings(settings))

    if rf_off_before_change:
        instrument.write(":OUTP OFF")
    instrument.write(f":SOUR:FREQ:CW {frequency}")
    instrument.write(f":SOUR:POW {power}")
    instrument.write(f":OUTP {'ON' if rf_output else 'OFF'}")
    settings = read_signal_generator_settings(instrument, idn)
    return AcquisitionResult(kind="signal_generator", file_type="csv", content=_format_signal_generator_settings(settings))


def set_signal_generator_rf_output(instrument: VisaInstrument, idn: str, enabled: bool) -> AcquisitionResult:
    profile = detect_profile(idn)
    if not profile.supports_signal_generator:
        raise NotImplementedError(f"Unsupported signal generator device: {idn}")
    LOGGER.info("SCPI action=signal_generator_rf profile=%s enabled=%s", profile.key, enabled)
    if profile.key == "rs_smg_legacy":
        instrument.write(f"LEVEL:RF:{'ON' if enabled else 'OFF'}")
        settings = read_signal_generator_settings(instrument, idn)
        return AcquisitionResult(kind="signal_generator", file_type="csv", content=_format_signal_generator_settings(settings))
    instrument.write(f":OUTP {'ON' if enabled else 'OFF'}")
    settings = read_signal_generator_settings(instrument, idn)
    return AcquisitionResult(kind="signal_generator", file_type="csv", content=_format_signal_generator_settings(settings))


def read_scope_measurement(instrument: VisaInstrument, measurement: str, channel: int, idn: str | None = None) -> AcquisitionResult:
    profile = detect_profile(idn or "")
    command = _scope_measurement_command(profile.key, measurement, channel)
    if command is None:
        raise ValueError(f"Unsupported scope measurement: {measurement}")
    LOGGER.info(
        "SCPI action=scope_measurement profile=%s measurement=%s channel=%s commands=%s",
        profile.key,
        measurement,
        channel,
        _command_summary(command),
    )
    if isinstance(command, tuple):
        setup, query = command
        _write_commands(instrument, setup)
        value = instrument.query(query).strip()
    else:
        value = instrument.query(command).strip()
    return AcquisitionResult(kind=f"scope {measurement} CH{channel}", file_type="value", content=value)


def _scope_measurement_command(profile_key: str, measurement: str, channel: int) -> str | tuple[tuple[str, ...], str] | None:
    keysight_commands = {
        "Vpp": f":MEASure:VPP? CHANnel{channel}",
        "Vrms": f":MEASure:VRMS? CHANnel{channel}",
        "Frequency": f":MEASure:FREQuency? CHANnel{channel}",
        "Period": f":MEASure:PERiod? CHANnel{channel}",
        "Vmax": f":MEASure:VMAX? CHANnel{channel}",
        "Vmin": f":MEASure:VMIN? CHANnel{channel}",
    }
    if profile_key in {"keysight_infinivision_x", "keysight_infinivision_6000", "keysight_infinivision_7000", "agilent_54600", "unknown"}:
        return keysight_commands.get(measurement)

    tektronix_types = {
        "Vpp": "PK2Pk",
        "Vrms": "RMS",
        "Frequency": "FREQuency",
        "Period": "PERIod",
        "Vmax": "MAXimum",
        "Vmin": "MINImum",
    }
    if profile_key in {"tektronix_mdo", "tektronix_tds30", "tektronix_tds400"}:
        measurement_type = tektronix_types.get(measurement)
        if measurement_type is None:
            return None
        return ((f"MEASUrement:IMMed:SOUrce CH{channel}", f"MEASUrement:IMMed:TYPe {measurement_type}"), "MEASUrement:IMMed:VALue?")

    lecroy_measurements = {
        "Vpp": "PKPK",
        "Vrms": "RMS",
        "Frequency": "FREQ",
        "Period": "PER",
        "Vmax": "MAX",
        "Vmin": "MIN",
    }
    if profile_key == "lecroy_xstream":
        parameter = lecroy_measurements.get(measurement)
        if parameter is None:
            return None
        return f"C{channel}:PAVA? {parameter}"

    rs_measurements = {
        "Vpp": "PEAK",
        "Vrms": "RMS",
        "Frequency": "FREQuency",
        "Period": "PERiod",
        "Vmax": "UPEakvalue",
        "Vmin": "LPEakvalue",
    }
    if profile_key == "rs_rt_scope":
        measurement_type = rs_measurements.get(measurement)
        if measurement_type is None:
            return None
        return ((f"MEASurement1:SOURce C{channel}", f"MEASurement1:MAIN {measurement_type}"), "MEASurement1:RESult:ACTual?")

    return keysight_commands.get(measurement)


SIMPLE_SCREENSHOTS = {
    "keysight_infinivision_x": SimpleScreenshotCommand(
        file_type="png",
        query=":DISPLAY:DATA? PNG, COLOR",
    ),
    "keysight_infinivision_6000": SimpleScreenshotCommand(
        file_type="png",
        query=":DISPLAY:DATA? PNG, COLOR",
    ),
    "keysight_infinivision_7000": SimpleScreenshotCommand(
        file_type="png",
        setup=(":HARD:INKS ON",),
        query=":DISP:DATA? PNG, SCR, COL",
        delay_s=2.0,
    ),
    "agilent_54600": SimpleScreenshotCommand(
        file_type="bmp",
        query=":DISPLAY:DATA? BMP, SCREEN",
    ),
    "tektronix_mdo": SimpleScreenshotCommand(
        file_type="png",
        setup=("SAVE:IMAG:FILEF PNG", "HARDCopy:INKS ON"),
        query="HARDCOPY START",
    ),
    "tektronix_tds30": SimpleScreenshotCommand(
        file_type="png",
        setup=("SAVE:IMAG:FILEF PNG", "HARD:INKS ON"),
        query="HARD:STAR",
    ),
    "tektronix_tds400": SimpleScreenshotCommand(
        file_type="tiff",
        setup=("HARDCopy:FORMat TIFF",),
        query="HARDCOPY START",
    ),
    "rs_hameg_hms": SimpleScreenshotCommand(
        file_type="bmp",
        setup=("HCOPy:FORMat BMP",),
        query="HCOPy:DATA?",
    ),
    "rs_rt_scope": SimpleScreenshotCommand(
        file_type="png",
        setup=("HCOPy:LANGuage PNG",),
        query="HCOPy:DATA?",
    ),
    "lecroy_xstream": SimpleScreenshotCommand(
        file_type="bmp",
        setup=("HARDCOPY_SETUP DEV,BMP,PORT,GPIB",),
        query="SCREEN_DUMP",
    ),
}


def capture_screenshot(instrument: VisaInstrument, idn: str, title: str = "") -> AcquisitionResult:
    profile = detect_profile(idn)
    LOGGER.info("SCPI action=screenshot profile=%s idn=%s", profile.key, idn)
    simple_command = _simple_screenshot_command(idn)
    if simple_command is not None:
        return _capture_simple_screenshot(instrument, simple_command)

    if profile.key in {"hp_e740", "hp_agilent_e4402b"}:
        _set_e740_date_time(instrument)
        if title:
            instrument.write(f":DISP:ANN:Title:Data '{title}'")
        instrument.write(":DISP:MENU:STATE 0")
        try:
            data = _store_read_delete_binary(
                instrument,
                store_command=":MMEM:STOR:SCR 'R:INTUI.WMF'",
                read_command=":MMEM:DATA? 'R:INTUI.WMF';*WAI",
                delete_command=":MMEM:DEL 'R:INTUI.WMF'",
            )
        finally:
            instrument.write(":DISP:MENU:STATE 1")
        return AcquisitionResult(kind="screenshot", file_type="wmf", content=data)

    if profile.key == "hp_8591a":
        data = _read_raw_after_write(instrument, "GETPLOT")
        return AcquisitionResult(kind="screenshot", file_type="hpgl", content=data)

    if profile.key == "keysight_e5071c":
        instrument.write(":DISP:MENU:STATE 0")
        instrument.write(":HCOP:SDUM:DATA:FORM PNG")
        display_status = instrument.query(":DISP:IMAG?").strip()
        menu_status = instrument.query(":DISP:SKEY:STAT?").strip()
        instrument.write(":DISP:IMAG INV")
        instrument.write(":DISP:SKEY:STAT 0")
        sleep(0.25)
        data = instrument.query_binary(":HCOP:SDUM:DATA?")
        instrument.write(f":DISP:IMAG {display_status}")
        instrument.write(f":DISP:SKEY:STAT {menu_status}")
        return AcquisitionResult(kind="screenshot", file_type="png", content=data)

    if profile.key == "rs_fsw":
        data = _store_read_binary(
            instrument,
            setup=(
                "HCOP:DEV:LANG PNG;*WAI",
                "HCOP:DEST1 MMEM;*WAI",
                "MMEM:NAME 'C:\\R_S\\Instr\\user\\screenshot.png';*WAI",
                "HCOP:PAGE:WIND:COUN;*WAI",
                "HCOP:CONT WIND 1;*WAI",
            ),
            store_command="HCOP;*WAI",
            read_command="MMEM:DATA? 'C:\\R_S\\Instr\\user\\screenshot.png';*WAI",
        )
        return AcquisitionResult(kind="screenshot", file_type="png", content=data)

    if profile.key == "keysight_n90":
        menu_status = instrument.query("DISP:FSCR:STAT?;*WAI").strip()
        instrument.write("DISP:FSCR:STAT 1;*WAI")
        sleep(0.2)
        try:
            data = _store_read_delete_binary(
                instrument,
                store_command="MMEM:STOR:SCR 'D:\\\\PICTURE.PNG';*WAI",
                read_command="MMEM:DATA? 'D:\\\\PICTURE.PNG';*WAI",
                delete_command="MMEM:DEL 'D:\\\\PICTURE.PNG';*WAI",
            )
        finally:
            instrument.write(f"DISP:FSCR:STAT {menu_status};*WAI")
        return AcquisitionResult(kind="screenshot", file_type="png", content=data)

    if profile.key == "rs_znb":
        data = _store_read_delete_binary(
            instrument,
            setup=(
                "HCOP:DEV:LANG PNG;*WAI",
                "MMEM:NAME 'C:\\Screenshots\\screenshot.png';*WAI",
                "HCOP:PAGE:WIND ACT",
            ),
            store_command="HCOP;*WAI",
            read_command="MMEM:DATA? 'C:\\Screenshots\\screenshot.png';*WAI",
            delete_command="MMEM:DEL 'C:\\Screenshots\\screenshot.png';*WAI",
        )
        return AcquisitionResult(kind="screenshot", file_type="png", content=data)

    raise NotImplementedError(f"Unsupported screenshot device: {idn}")


def capture_waveform(
    instrument: VisaInstrument,
    idn: str,
    channels: list[int] | None = None,
    point_mode: str = "RAW",
) -> AcquisitionResult:
    profile = detect_profile(idn)
    LOGGER.info("SCPI action=waveform profile=%s channels=%s point_mode=%s", profile.key, channels, point_mode)

    if profile.key in {"hp_e740", "hp_agilent_e4402b"}:
        _set_e740_date_time(instrument)
        instrument.write(":DISP:MENU:STATE 0")
        try:
            content = _store_read_delete_text(
                instrument,
                store_command=':MMEM:STOR:TRAC TRACE1,"R:INTUI.CSV"',
                read_command=":MMEM:DATA? 'R:INTUI.CSV'",
                delete_command=":MMEM:DEL 'R:INTUI.CSV'",
            )
        finally:
            instrument.write(":DISP:MENU:STATE 1")
        return AcquisitionResult(kind="waveform", file_type="csv", content=_strip_ieee_header(content))

    if profile.key == "hp_8591a":
        content = _capture_hp_8591a_trace(instrument)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    if profile.key == "hp_4395a":
        instrument.write("FORM4")
        frequency_data = instrument.query("OUTPSWPRM?").strip()
        trace_data = instrument.query("OUTPDTRC?").strip()
        complex_data = instrument.query("OUTPDATA?").strip()
        content = _format_4395a_waveform(frequency_data, trace_data, complex_data)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    if profile.key in {"keysight_infinivision_x", "keysight_infinivision_6000", "keysight_infinivision_7000"}:
        content = _capture_3000x_waveform(instrument, channels, point_mode)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    if profile.key == "agilent_54600":
        content = _capture_agilent_54600_waveform(instrument, channels)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    if profile.key in {"keysight_344_l44", "keithley_2000"}:
        return read_value(instrument)

    if profile.key == "tektronix_tds400":
        content = _capture_ascii_waveform(instrument, channels)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    if profile.key == "rs_rt_scope":
        content = _capture_rs_rt_waveform(instrument, channels)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    if profile.key == "rs_hameg_hms":
        content = _capture_hms_trace(instrument)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    if profile.key == "lecroy_xstream":
        content = _capture_lecroy_waveform(instrument, channels)
        return AcquisitionResult(kind="waveform", file_type="csv", content=content)

    raise NotImplementedError(f"Unsupported waveform device: {idn}")


def capture_sparameters(instrument: VisaInstrument, idn: str, config: SParameterConfig) -> AcquisitionResult:
    profile = detect_profile(idn)
    LOGGER.info("SCPI action=sparameters profile=%s ports=%s format=%s", profile.key, config.selected_ports, config.format)
    ports = config.selected_ports
    if not ports:
        raise ValueError("At least one S-parameter port must be selected")

    if profile.key == "keysight_e5071c":
        file_type = f"s{len(ports)}p"
        port_list = ",".join(str(port) for port in ports)
        content = _store_read_delete_text(
            instrument,
            setup=(
                ":SYST:BEEP:COMP:STAT OFF",
                f":MMEM:STOR:SNP:FORM {config.format}; *WAI",
                f":MMEM:STOR:SNP:TYPE:S{len(ports)}P {port_list};*WAI",
            ),
            store_command=f":MMEM:STOR:SNP 'D:\\SNP01.{file_type}';*WAI",
            read_command=f":MMEM:TRAN? 'D:\\SNP01.{file_type}';*WAI",
            delete_command=f":MMEM:DEL 'D:\\SNP01.{file_type}';*WAI",
        )
        return AcquisitionResult(kind="sparameters", file_type=file_type, content=_strip_ieee_header(content))

    if profile.key == "rs_znb":
        file_type = f"s{len(ports)}p"
        znb_format = {"DB": "LOGP", "AUTO": "COMP", "RI": "COMP", "MA": "LINP"}.get(config.format, config.format)
        active_channel = instrument.query("INST:NSEL?").strip()
        port_count = len(instrument.query("SOUR:GRO:PPOR?").strip().split(","))
        if len(ports) > port_count:
            raise ValueError(f"Selected {len(ports)} ports, but instrument reports only {port_count} active ports")
        port_list = ",".join(str(port) for port in ports)
        content = _store_read_delete_text(
            instrument,
            setup=("MMEM:CDIR DEF",),
            store_command=f"MMEM:STOR:TRAC:PORT {active_channel}, 'Traces\\visatmp.{file_type}', {znb_format}, CIMP, {port_list}",
            read_command=f"MMEM:DATA? 'Traces\\visatmp.{file_type}'",
            delete_command=f"MMEM:DEL 'Traces\\visatmp.{file_type}'",
        )
        return AcquisitionResult(kind="sparameters", file_type=file_type, content=_strip_ieee_header(content))

    raise NotImplementedError(f"Unsupported S-parameter device: {idn}")


def _simple_screenshot_command(idn: str) -> SimpleScreenshotCommand | None:
    profile = detect_profile(idn)
    if profile.key in SIMPLE_SCREENSHOTS:
        return SIMPLE_SCREENSHOTS[profile.key]
    return None


def _capture_simple_screenshot(instrument: VisaInstrument, command: SimpleScreenshotCommand) -> AcquisitionResult:
    LOGGER.info(
        "SCPI action=simple_screenshot file_type=%s setup=%s query=%s cleanup=%s",
        command.file_type,
        command.setup,
        command.query,
        command.cleanup,
    )
    _write_commands(instrument, command.setup)
    if command.delay_s:
        sleep(command.delay_s)
    try:
        data = _normalize_image_bytes(instrument.query_binary(command.query), command.file_type)
    finally:
        _write_commands(instrument, command.cleanup)
    return AcquisitionResult(kind="screenshot", file_type=command.file_type, content=data)


def _store_read_binary(
    instrument: VisaInstrument,
    *,
    store_command: str,
    read_command: str,
    setup: tuple[str, ...] = (),
) -> bytes:
    _write_commands(instrument, setup)
    instrument.write(store_command)
    return instrument.query_binary(read_command)


def _store_read_delete_binary(
    instrument: VisaInstrument,
    *,
    store_command: str,
    read_command: str,
    delete_command: str,
    setup: tuple[str, ...] = (),
) -> bytes:
    _write_commands(instrument, setup)
    instrument.write(store_command)
    try:
        return instrument.query_binary(read_command)
    finally:
        instrument.write(delete_command)


def _store_read_delete_text(
    instrument: VisaInstrument,
    *,
    store_command: str,
    read_command: str,
    delete_command: str,
    setup: tuple[str, ...] = (),
) -> str:
    _write_commands(instrument, setup)
    try:
        instrument.write(store_command)
        return instrument.query(read_command)
    finally:
        instrument.write(delete_command)


def _read_raw_after_write(instrument: VisaInstrument, command: str) -> bytes:
    if hasattr(instrument, "read_raw_after_write"):
        return instrument.read_raw_after_write(command)  # type: ignore[attr-defined]
    instrument.write(command)
    if hasattr(instrument, "read_raw"):
        return instrument.read_raw()  # type: ignore[attr-defined]
    raise NotImplementedError("Instrument does not support raw read after write")


def _write_commands(instrument: VisaInstrument, commands: tuple[str, ...]) -> None:
    for command in commands:
        LOGGER.info("SCPI write command=%s", command)
        instrument.write(command)


def _set_e740_date_time(instrument: VisaInstrument) -> None:
    now = datetime.now()
    instrument.write(f":SYST:TIME {now.hour},{now.minute},{now.second}")
    instrument.write(f":SYST:DATE {now.year},{now.month},{now.day}")


def _strip_ieee_header(content: str) -> str:
    if not content.startswith("#") or len(content) < 3 or not content[1].isdigit():
        return content
    digits = int(content[1])
    return content[2 + digits :]


def _strip_ieee_binary_header(content: bytes) -> bytes:
    if not content.startswith(b"#") or len(content) < 3 or not chr(content[1]).isdigit():
        return content
    digits = int(chr(content[1]))
    header_end = 2 + digits
    if len(content) < header_end:
        return content
    return content[header_end:]


def _normalize_image_bytes(content: bytes, file_type: str) -> bytes:
    stripped = _strip_ieee_binary_header(content)
    magic_offsets = _image_magic_offsets(stripped, file_type)
    if magic_offsets:
        return stripped[min(magic_offsets) :]

    magic_offsets = _image_magic_offsets(content, file_type)
    if magic_offsets:
        return content[min(magic_offsets) :]

    return stripped


def _image_magic_offsets(content: bytes, file_type: str) -> list[int]:
    file_type = file_type.lower()
    signatures: tuple[bytes, ...]
    if file_type == "png":
        signatures = (b"\x89PNG\r\n\x1a\n",)
    elif file_type == "bmp":
        signatures = (b"BM",)
    elif file_type in {"tif", "tiff"}:
        signatures = (b"II*\x00", b"MM\x00*")
    else:
        signatures = ()
    return [offset for signature in signatures if (offset := content.find(signature)) >= 0]


def _command_summary(command: str | tuple[tuple[str, ...], str]) -> str:
    if isinstance(command, tuple):
        setup, query = command
        return "; ".join([*setup, query])
    return command


def _normalize_rf_state(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"1", "+1", "ON"}:
        return "ON"
    if normalized in {"0", "+0", "OFF"}:
        return "OFF"
    return value.strip()


def _strip_prefixed_value(value: str, prefix: str) -> str:
    stripped = value.strip()
    if stripped.upper().startswith(prefix.upper()):
        stripped = stripped[len(prefix) :].strip()
        if stripped.startswith(":"):
            stripped = stripped[1:].strip()
        return stripped
    return stripped


def _parse_dbm(value: str) -> float:
    normalized = value.strip().upper().replace(" ", "")
    for suffix in ("DBM", "DB"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    try:
        return float(normalized.replace(",", "."))
    except ValueError as exc:
        raise ValueError("Power must be a dBm value, for example -30 dBm") from exc


def _parse_float_with_suffix(value: str, suffixes: tuple[str, ...]) -> float:
    normalized = value.strip().upper().replace(" ", "")
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    try:
        return float(normalized.replace(",", "."))
    except ValueError as exc:
        suffix_text = "/".join(suffixes)
        raise ValueError(f"Value must be numeric with optional {suffix_text} suffix") from exc


def _validate_power_supply_channel(channel: int, idn: str = "") -> None:
    max_channel = hmp_channel_count(idn)
    if channel < 1 or channel > max_channel:
        raise ValueError(f"Power supply channel must be between 1 and {max_channel}")


def _format_signal_generator_settings(settings: SignalGeneratorSettings) -> str:
    rows = [
        ["Setting", "Value"],
        ["Frequency", settings.frequency],
        ["Power", settings.power],
        ["RFOutput", settings.rf_output],
    ]
    return "\n".join(",".join(row) for row in rows)


def _format_power_supply_settings(settings: PowerSupplySettings) -> str:
    rows = [
        ["Setting", "Value"],
        ["Channel", str(settings.channel)],
        ["VoltageSet", settings.voltage_set],
        ["CurrentSet", settings.current_set],
        ["VoltageMeasured", settings.voltage_measured],
        ["CurrentMeasured", settings.current_measured],
        ["OutputSelected", settings.output_selected],
        ["OutputGeneral", settings.output_general],
    ]
    return "\n".join(",".join(row) for row in rows)


def _format_4395a_waveform(frequency_data: str, trace_data: str, complex_data: str) -> str:
    trace_values = _split_numeric_series(trace_data)
    complex_sections = [section for section in complex_data.replace("\r", "\n").split("\n") if section.strip()]
    complex_a = _split_numeric_series(complex_sections[0] if complex_sections else "")
    complex_b = _split_numeric_series(complex_sections[1] if len(complex_sections) > 1 else "")

    magnitude_1 = trace_values[0::2]
    magnitude_2 = trace_values[1::2]
    complex_1 = complex_a[0::2]
    complex_2 = complex_a[1::2]
    complex_3 = complex_b[0::2]
    complex_4 = complex_b[1::2]

    rows = [
        ["Frequency", *_split_numeric_series(frequency_data)],
        ["Magnitude1", *magnitude_1],
        ["Magnitude2", *magnitude_2],
        ["Komplex1", *complex_1],
        ["Komplex2", *complex_2],
        ["Komplex3", *complex_3],
        ["Komplex4", *complex_4],
    ]
    return "\n".join(",".join(row) for row in rows)


def _split_numeric_series(value: str) -> list[str]:
    normalized = value.replace("\r", ",").replace("\n", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def _capture_3000x_waveform(
    instrument: VisaInstrument,
    selected_channels: list[int] | None = None,
    point_mode: str = "RAW",
) -> str:
    point_mode = point_mode.upper()
    if point_mode not in {"RAW", "NORMAL", "MAXIMUM"}:
        raise ValueError(f"Unsupported waveform point mode: {point_mode}")

    channels: dict[str, list[str]] = {}
    time_axis: list[str] = []
    channel_numbers = selected_channels or [1, 2, 3, 4]
    display_states: dict[int, str] = {}
    channel_status: list[str] = []

    try:
        for channel in channel_numbers:
            if channel not in {1, 2, 3, 4}:
                raise ValueError(f"Invalid channel: {channel}")

            display_state = instrument.query(f":CHANnel{channel}:DISPlay?").strip().upper()
            display_states[channel] = display_state
            if selected_channels is None and display_state not in {"1", "+1", "ON"}:
                continue
            if selected_channels is not None and display_state not in {"1", "+1", "ON"}:
                instrument.write(f":CHANnel{channel}:DISPlay ON")
                sleep(0.2)

            values, channel_error = _read_3000x_channel_waveform(instrument, channel, point_mode)
            channels[f"CH{channel}"] = values
            channel_status.append(f"CH{channel}: {len(values)} Punkte, Fehler: {channel_error}")
            if not values:
                continue
            if not time_axis:
                x_increment = float(instrument.query(":WAVeform:XINCrement?").strip())
                x_reference = float(instrument.query(":WAVeform:XREFerence?").strip())
                x_origin = float(instrument.query(":WAVeform:XORigin?").strip())
                time_axis = [str(((index - x_reference) * x_increment) + x_origin) for index in range(len(values))]
    finally:
        if selected_channels is not None:
            for channel, display_state in display_states.items():
                if display_state in {"0", "+0", "OFF"}:
                    instrument.write(f":CHANnel{channel}:DISPlay OFF")

    error = instrument.query(":SYSTEM:ERROR?").strip()
    if not channels:
        return f"SystemError,{error}\n"

    headers = ["Time", *channels.keys()]
    rows = [["WaveformStatus", *channel_status], ["PointMode", point_mode], [], headers]
    max_points = max(len(values) for values in channels.values())
    for index in range(max_points):
        row = [time_axis[index] if index < len(time_axis) else ""]
        row.extend(values[index] if index < len(values) else "" for values in channels.values())
        rows.append(row)

    rows.append([])
    rows.append(["SystemError", error])
    return "\n".join(",".join(row) for row in rows)


def _read_3000x_channel_waveform(instrument: VisaInstrument, channel: int, point_mode: str) -> tuple[list[str], str]:
    instrument.write(f":WAVeform:SOURce CHANnel{channel}")
    instrument.write(":WAVeform:FORMat ASCII")
    instrument.write(f":WAVeform:POINts:MODE {point_mode}")
    values = _split_numeric_series(_strip_ieee_header(instrument.query(":WAVeform:DATA?")).lstrip())
    channel_error = instrument.query(":SYSTem:ERRor?").strip()
    return values, channel_error


def _capture_agilent_54600_waveform(instrument: VisaInstrument, selected_channels: list[int] | None = None) -> str:
    channels: dict[str, list[str]] = {}
    time_axis: list[str] = []
    channel_numbers = selected_channels or [1, 2]
    for channel in channel_numbers:
        instrument.write(f":WAVeform:SOURce CHANnel{channel}")
        instrument.write(":WAVeform:FORMat ASCII")
        values = _split_numeric_series(_strip_ieee_header(instrument.query(":WAVeform:DATA?")).lstrip())
        channels[f"CH{channel}"] = values
        if values and not time_axis:
            x_increment = float(instrument.query(":WAVeform:XINCrement?").strip())
            x_reference = float(instrument.query(":WAVeform:XREFerence?").strip())
            x_origin = float(instrument.query(":WAVeform:XORigin?").strip())
            time_axis = [str(((index - x_reference) * x_increment) + x_origin) for index in range(len(values))]
    return _format_channel_rows(channels, time_axis)


def _capture_ascii_waveform(instrument: VisaInstrument, selected_channels: list[int] | None = None) -> str:
    channels: dict[str, list[str]] = {}
    channel_numbers = selected_channels or [1, 2, 3, 4]
    for channel in channel_numbers:
        instrument.write(f"DATa:SOUrce CH{channel}")
        instrument.write("DATa:ENCdg ASCii")
        values = _split_numeric_series(_strip_ieee_header(instrument.query("CURVE?")).lstrip())
        channels[f"CH{channel}"] = values
    return _format_channel_rows(channels)


def _capture_rs_rt_waveform(instrument: VisaInstrument, selected_channels: list[int] | None = None) -> str:
    channels: dict[str, list[str]] = {}
    channel_numbers = selected_channels or [1, 2, 3, 4]
    instrument.write("FORMat ASCii")
    for channel in channel_numbers:
        values = _split_numeric_series(instrument.query(f"CHANnel{channel}:DATA?").strip())
        channels[f"CH{channel}"] = values
    return _format_channel_rows(channels)


def _capture_hms_trace(instrument: VisaInstrument) -> str:
    instrument.write("TRACe:DATA:FORMat CSV")
    content = instrument.query("TRAC:DATA?").strip()
    return "Trace\n" + _strip_ieee_header(content).lstrip()


def _capture_hp_8591a_trace(instrument: VisaInstrument) -> str:
    trace_values = _split_numeric_series(_strip_ieee_header(instrument.query("TRA?")).lstrip())
    return "Point,TraceA\n" + "\n".join(f"{index},{value}" for index, value in enumerate(trace_values, start=1))


def _capture_lecroy_waveform(instrument: VisaInstrument, selected_channels: list[int] | None = None) -> str:
    channels: dict[str, list[str]] = {}
    channel_numbers = selected_channels or [1, 2, 3, 4]
    for channel in channel_numbers:
        values = _split_numeric_series(instrument.query(f'C{channel}:INSPECT? "SIMPLE"').strip())
        channels[f"CH{channel}"] = values
    return _format_channel_rows(channels)


def _format_channel_rows(channels: dict[str, list[str]], time_axis: list[str] | None = None) -> str:
    if not channels:
        return ""
    headers = list(channels)
    rows = [[*( ["Time"] if time_axis else []), *headers]]
    max_points = max(len(values) for values in channels.values())
    for index in range(max_points):
        row = [time_axis[index] if time_axis and index < len(time_axis) else ""] if time_axis else []
        row.extend(channels[channel][index] if index < len(channels[channel]) else "" for channel in headers)
        rows.append(row)
    return "\n".join(",".join(row) for row in rows)
