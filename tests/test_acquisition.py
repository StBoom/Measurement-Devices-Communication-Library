from __future__ import annotations

import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from instrument_visa.acquisition import (  # noqa: E402
    AcquisitionResult,
    capture_screenshot,
    capture_waveform,
    read_power_supply_settings,
    read_signal_generator_settings,
    read_scope_measurement,
    read_value,
    set_power_supply,
    set_power_supply_master_output,
    set_power_supply_output,
    set_signal_generator,
    set_signal_generator_rf_output,
)
from instrument_visa.excel_export import append_result  # noqa: E402
from instrument_visa.cli import _load_sequence_config  # noqa: E402
from instrument_visa.picoscope_client import parse_pico_analog_channels, parse_pico_digital_channels  # noqa: E402
from instrument_visa.profiles import detect_profile  # noqa: E402
from instrument_visa.sequence import (  # noqa: E402
    CustomSequenceConfig,
    MAX_SWEEP_POINTS,
    FrequencySweepConfig,
    SequenceStep,
    SequenceVariable,
    TimedSwitchConfig,
    VoltageSweepConfig,
    frequency_points,
    parse_json_bool,
    parse_frequency_hz,
    parse_serial_format,
    parse_parallel_tasks,
    read_direct_serial_log,
    parse_34970a_channels,
    read_34970a_data_logger,
    DataLogger34970AConfig,
    parse_34970a_measurement_plan,
    run_custom_sequence,
    run_frequency_sweep,
    run_timed_switch,
    run_voltage_sweep,
    voltage_points,
)


class FakeInstrument:
    def __init__(self, query_responses: dict[str, str] | None = None, binary_responses: dict[str, bytes] | None = None) -> None:
        self.address = "USB::TEST"
        self.query_responses = query_responses or {}
        self.binary_responses = binary_responses or {}
        self.raw_responses: dict[str, bytes] = {}
        self.serial_log_responses: dict[float, str] = {}
        self.pico_analog_configs: list[object] = []
        self.pico_digital_configs: list[object] = []
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.binary_queries: list[str] = []
        self.raw_writes: list[str] = []
        self.serial_log_durations: list[float] = []
        self.serial_log_baudrates: list[int | None] = []
        self.serial_configs: list[tuple[int | None, int | None, str | None, float | None]] = []

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        return self.query_responses.get(command, "1.23")

    def query_binary(self, command: str) -> bytes:
        self.binary_queries.append(command)
        return self.binary_responses.get(command, b"DATA")

    def read_raw_after_write(self, command: str) -> bytes:
        self.raw_writes.append(command)
        return self.raw_responses.get(command, b"IN;SP1;PU0,0;PD100,100;")

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
        self.serial_log_durations.append(duration_s)
        self.serial_log_baudrates.append(baudrate)
        return self.serial_log_responses.get(duration_s, "serial line 1\nserial line 2")

    def info(self):
        from instrument_visa.visa_client import InstrumentInfo

        return InstrumentInfo(address=self.address, idn=self.query("*IDN?").strip())

    def configure_serial(self, baudrate: int | None = None, bytesize: int | None = None, parity: str | None = None, stopbits: float | None = None) -> None:
        self.serial_configs.append((baudrate, bytesize, parity, stopbits))

    def capture_analog(self, config, stop_requested=None):
        self.pico_analog_configs.append(config)
        return AcquisitionResult(kind="picoscope analog", file_type="csv", content="Time_s,A_V\n0,1.0\n")

    def capture_digital(self, config, stop_requested=None):
        self.pico_digital_configs.append(config)
        return AcquisitionResult(kind="picoscope digital", file_type="csv", content="Time_s,D0\n0,1\n")


class AcquisitionTests(unittest.TestCase):
    def test_profile_detection_for_new_manual_checked_devices(self) -> None:
        cases = {
            "AGILENT TECHNOLOGIES,MSO6034A,MY123,1.0": "keysight_infinivision_6000",
            "AGILENT TECHNOLOGIES,DSO7034B,MY123,1.0": "keysight_infinivision_7000",
            "AGILENT TECHNOLOGIES,54622D,MY123,1.0": "agilent_54600",
            "TEKTRONIX,TDS420A,0,CF:91.1CT": "tektronix_tds400",
            "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0": "keithley_2000",
            "ROHDE&SCHWARZ,HMS-X,123,1.0": "rs_hameg_hms",
            "LECROY,WAVERUNNER 610ZI,123,1.0": "lecroy_xstream",
            "ROHDE&SCHWARZ,RTB2004,123,1.0": "rs_rt_scope",
            "HEWLETT-PACKARD,8591A,123,1.0": "hp_8591a",
            "AGILENT TECHNOLOGIES,E4402B,US123,1.0": "hp_agilent_e4402b",
            "Rohde&Schwarz,SMIQ03B,123,1.0": "rs_sme_smt_smiq",
            "Rohde&Schwarz,SMHU,123,1.0": "rs_smg_legacy",
            "HAMEG,HMP4030,123,1.0": "rs_hmp_power_supply",
            "HEWLETT-PACKARD,34970A,0,13-2-2": "keysight_34970a",
        }

        for idn, expected_key in cases.items():
            with self.subTest(idn=idn):
                self.assertEqual(detect_profile(idn).key, expected_key)

    def test_keithley_2000_dmm_uses_read_query(self) -> None:
        instrument = FakeInstrument(query_responses={":READ?": "4.56"})

        result = read_value(instrument)  # type: ignore[arg-type]

        self.assertEqual(result.content, "4.56")
        self.assertEqual(instrument.queries, [":READ?"])

    def test_hms_x_trace_uses_csv_format_before_data_query(self) -> None:
        instrument = FakeInstrument(query_responses={"TRAC:DATA?": "[Hz],Trace1[dBm]\n1.0,-2.0"})

        result = capture_waveform(instrument, "ROHDE&SCHWARZ,HMS-X,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(result.file_type, "csv")
        self.assertEqual(instrument.writes, ["TRACe:DATA:FORMat CSV"])
        self.assertEqual(instrument.queries, ["TRAC:DATA?"])
        self.assertIn("[Hz],Trace1[dBm]", str(result.content))

    def test_e4402b_uses_e740_style_trace_export(self) -> None:
        instrument = FakeInstrument(query_responses={":MMEM:DATA? 'R:INTUI.CSV'": "Frequency,Trace\n1.0,-20.0"})

        result = capture_waveform(instrument, "AGILENT TECHNOLOGIES,E4402B,US123,1.0")  # type: ignore[arg-type]

        self.assertEqual(result.file_type, "csv")
        self.assertEqual(result.content, "Frequency,Trace\n1.0,-20.0")
        self.assertTrue(instrument.writes[0].startswith(":SYST:TIME "))
        self.assertTrue(instrument.writes[1].startswith(":SYST:DATE "))
        self.assertEqual(
            instrument.writes[2:],
            [":DISP:MENU:STATE 0", ':MMEM:STOR:TRAC TRACE1,"R:INTUI.CSV"', ":MMEM:DEL 'R:INTUI.CSV'", ":DISP:MENU:STATE 1"],
        )
        self.assertEqual(instrument.queries, [":MMEM:DATA? 'R:INTUI.CSV'"])

    def test_hp_8591a_trace_uses_legacy_trace_query(self) -> None:
        instrument = FakeInstrument(query_responses={"TRA?": "-10,-20,-30"})

        result = capture_waveform(instrument, "HEWLETT-PACKARD,8591A,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(result.file_type, "csv")
        self.assertEqual(result.content, "Point,TraceA\n1,-10\n2,-20\n3,-30")
        self.assertEqual(instrument.queries, ["TRA?"])

    def test_hp_8591a_screenshot_uses_getplot_hpgl(self) -> None:
        instrument = FakeInstrument()
        instrument.raw_responses["GETPLOT"] = b"IN;SP1;PU0,0;PD100,100;"

        result = capture_screenshot(instrument, "HEWLETT-PACKARD,8591A,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(result.file_type, "hpgl")
        self.assertEqual(result.content, b"IN;SP1;PU0,0;PD100,100;")
        self.assertEqual(instrument.raw_writes, ["GETPLOT"])

    def test_signal_generator_read_uses_basic_scpi_queries(self) -> None:
        instrument = FakeInstrument(query_responses={":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "1"})

        settings = read_signal_generator_settings(instrument, "Rohde&Schwarz,SMIQ03B,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(settings.frequency, "100000000")
        self.assertEqual(settings.power, "-30")
        self.assertEqual(settings.rf_output, "ON")
        self.assertEqual(instrument.queries, [":SOUR:FREQ:CW?", ":SOUR:POW?", ":OUTP?"])

    def test_signal_generator_set_switches_rf_off_before_change(self) -> None:
        instrument = FakeInstrument(query_responses={":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "0"})

        result = set_signal_generator(instrument, "Rohde&Schwarz,SMIQ03B,123,1.0", "100 MHz", "-30 dBm", False, 0.0, True)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, [":OUTP OFF", ":SOUR:FREQ:CW 100 MHz", ":SOUR:POW -30 dBm", ":OUTP OFF"])
        self.assertIn("Frequency,100000000", str(result.content))

    def test_signal_generator_rejects_power_above_limit(self) -> None:
        instrument = FakeInstrument()

        with self.assertRaises(ValueError):
            set_signal_generator(instrument, "Rohde&Schwarz,SMIQ03B,123,1.0", "100 MHz", "10 dBm", True, 0.0, True)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, [])

    def test_signal_generator_rf_off_command(self) -> None:
        instrument = FakeInstrument(query_responses={":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "0"})

        result = set_signal_generator_rf_output(instrument, "Rohde&Schwarz,SMIQ03B,123,1.0", False)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, [":OUTP OFF"])
        self.assertIn("RFOutput,OFF", str(result.content))

    def test_smg_legacy_generator_uses_manual_iec_commands(self) -> None:
        instrument = FakeInstrument(query_responses={"RF?": "RF 123456000", "LEVEL:RF?": "LEVEL:RF -20"})

        result = set_signal_generator(instrument, "Rohde&Schwarz,SMHU,123,1.0", "123.456MHz", "-20DBM", True, 0.0, True)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, ["LEVEL:RF:OFF", "RF 123.456MHz", "LEVEL:RF -20DBM", "LEVEL:RF:ON"])
        self.assertEqual(instrument.queries, ["RF?", "LEVEL:RF?"])
        self.assertIn("Frequency,123456000", str(result.content))
        self.assertIn("Power,-20", str(result.content))
        self.assertIn("RFOutput,ON", str(result.content))

    def test_smg_legacy_generator_reads_off_state(self) -> None:
        instrument = FakeInstrument(query_responses={"RF?": "RF 123456000", "LEVEL:RF?": "LEVEL:RF:OFF"})

        settings = read_signal_generator_settings(instrument, "Rohde&Schwarz,SMGU,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(settings.frequency, "123456000")
        self.assertEqual(settings.power, "OFF")
        self.assertEqual(settings.rf_output, "OFF")

    def test_hmp4030_power_supply_read_uses_selected_channel(self) -> None:
        instrument = FakeInstrument(
            query_responses={
                "VOLT?": "5.000",
                "CURR?": "0.500",
                "MEAS:VOLT?": "4.998",
                "MEAS:CURR?": "0.123",
                "OUTP:SEL?": "1",
                "OUTP:GEN?": "1",
            }
        )

        settings = read_power_supply_settings(instrument, "HAMEG,HMP4030,123,1.0", 2)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, ["INST:NSEL 2"])
        self.assertEqual(instrument.queries, ["VOLT?", "CURR?", "MEAS:VOLT?", "MEAS:CURR?", "OUTP:SEL?", "OUTP:GEN?"])
        self.assertEqual(settings.voltage_set, "5.000")
        self.assertEqual(settings.output_selected, "ON")

    def test_hmp4030_power_supply_set_uses_safe_channel_sequence(self) -> None:
        instrument = FakeInstrument(
            query_responses={
                "VOLT?": "5.000",
                "CURR?": "0.500",
                "MEAS:VOLT?": "4.998",
                "MEAS:CURR?": "0.123",
                "OUTP:SEL?": "1",
                "OUTP:GEN?": "1",
            }
        )

        result = set_power_supply(instrument, "HAMEG,HMP4030,123,1.0", 1, "5 V", "0.5 A", True, 10, 1)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes[:5], ["INST:NSEL 1", "VOLT 5 V", "CURR 0.5 A", "OUTP:SEL 1", "OUTP:GEN 1"])
        self.assertIn("VoltageMeasured,4.998", str(result.content))

    def test_hmp4030_rejects_voltage_above_limit_before_writes(self) -> None:
        instrument = FakeInstrument()

        with self.assertRaises(ValueError):
            set_power_supply(instrument, "HAMEG,HMP4030,123,1.0", 1, "20 V", "0.5 A", True, 10, 1)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, [])

    def test_hmp4030_rejects_invalid_channel_before_writes(self) -> None:
        instrument = FakeInstrument()

        with self.assertRaises(ValueError):
            set_power_supply(instrument, "HAMEG,HMP4030,123,1.0", 4, "5 V", "0.5 A", True, 10, 1)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, [])

    def test_hmp2020_rejects_channel_three_before_writes(self) -> None:
        instrument = FakeInstrument()

        with self.assertRaises(ValueError):
            read_power_supply_settings(instrument, "HAMEG,HMP2020,123,1.0", 3)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, [])

    def test_hmp4030_rejects_negative_voltage_and_current(self) -> None:
        instrument = FakeInstrument()

        with self.assertRaises(ValueError):
            set_power_supply(instrument, "HAMEG,HMP4030,123,1.0", 1, "-1 V", "0.5 A", True, 10, 1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            set_power_supply(instrument, "HAMEG,HMP4030,123,1.0", 1, "5 V", "-0.5 A", True, 10, 1)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes, [])

    def test_hmp4030_power_supply_output_off(self) -> None:
        instrument = FakeInstrument(
            query_responses={
                "VOLT?": "5.000",
                "CURR?": "0.500",
                "MEAS:VOLT?": "0.000",
                "MEAS:CURR?": "0.000",
                "OUTP:SEL?": "0",
                "OUTP:GEN?": "1",
            }
        )

        result = set_power_supply_output(instrument, "HAMEG,HMP4030,123,1.0", 3, False)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes[:2], ["INST:NSEL 3", "OUTP:SEL 0"])
        self.assertIn("OutputSelected,OFF", str(result.content))

    def test_hmp4030_power_supply_master_output_off(self) -> None:
        instrument = FakeInstrument(
            query_responses={
                "VOLT?": "5.000",
                "CURR?": "0.500",
                "MEAS:VOLT?": "0.000",
                "MEAS:CURR?": "0.000",
                "OUTP:SEL?": "0",
                "OUTP:GEN?": "0",
            }
        )

        result = set_power_supply_master_output(instrument, "HAMEG,HMP4030,123,1.0", False, 1)  # type: ignore[arg-type]

        self.assertEqual(instrument.writes[:2], ["OUTP:GEN 0", "INST:NSEL 1"])
        self.assertIn("OutputGeneral,OFF", str(result.content))

    def test_hms_x_screenshot_normalizes_ieee_bmp_block(self) -> None:
        payload = b"#6000010BM12345678"
        instrument = FakeInstrument(binary_responses={"HCOPy:DATA?": payload})

        result = capture_screenshot(instrument, "ROHDE&SCHWARZ,HMS-X,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(result.file_type, "bmp")
        self.assertEqual(result.content, b"BM12345678")
        self.assertEqual(instrument.writes, ["HCOPy:FORMat BMP"])
        self.assertEqual(instrument.binary_queries, ["HCOPy:DATA?"])

    def test_tektronix_tds400_measurement_commands_are_manual_style(self) -> None:
        instrument = FakeInstrument(query_responses={"MEASUrement:IMMed:VALue?": "1.0"})

        result = read_scope_measurement(instrument, "Vrms", 2, "TEKTRONIX,TDS420A,0,CF:91.1CT")  # type: ignore[arg-type]

        self.assertEqual(result.content, "1.0")
        self.assertEqual(instrument.writes, ["MEASUrement:IMMed:SOUrce CH2", "MEASUrement:IMMed:TYPe RMS"])
        self.assertEqual(instrument.queries, ["MEASUrement:IMMed:VALue?"])

    def test_rs_rt_scope_measurement_commands_are_manual_style(self) -> None:
        instrument = FakeInstrument(query_responses={"MEASurement1:RESult:ACTual?": "2.0"})

        result = read_scope_measurement(instrument, "Vpp", 1, "ROHDE&SCHWARZ,RTB2004,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(result.content, "2.0")
        self.assertEqual(instrument.writes, ["MEASurement1:SOURce C1", "MEASurement1:MAIN PEAK"])
        self.assertEqual(instrument.queries, ["MEASurement1:RESult:ACTual?"])

    def test_lecroy_screenshot_normalizes_bmp_after_prefix(self) -> None:
        instrument = FakeInstrument(binary_responses={"SCREEN_DUMP": b"LECROY HEADER BMabcdef"})

        result = capture_screenshot(instrument, "LECROY,WAVERUNNER 610ZI,123,1.0")  # type: ignore[arg-type]

        self.assertEqual(result.file_type, "bmp")
        self.assertEqual(result.content, b"BMabcdef")
        self.assertEqual(instrument.writes, ["HARDCOPY_SETUP DEV,BMP,PORT,GPIB"])
        self.assertEqual(instrument.binary_queries, ["SCREEN_DUMP"])

    def test_waveform_export_adds_excel_chart(self) -> None:
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "results.xlsx"
            result = AcquisitionResult(kind="waveform", file_type="csv", content="Time,CH1,CH2\n0,1,2\n1,3,4\n")

            export = append_result(workbook_path, "USB::TEST", "TEST,DSOX2024A,1,1", result)
            workbook = load_workbook(export.workbook_path)
            sheet = workbook[export.sheet_name]

            self.assertEqual(sheet["A7"].value, "Time")
            self.assertEqual(sheet["B8"].value, 1.0)
            self.assertEqual(len(sheet._charts), 1)
            self.assertEqual(sheet.freeze_panes, "A8")

    def test_large_waveform_export_adds_min_max_extract_for_chart(self) -> None:
        from openpyxl import load_workbook

        rows = ["Time,CH1"]
        for index in range(2500):
            value = 100 if index == 1999 else index % 10
            rows.append(f"{index},{value}")

        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "results.xlsx"
            result = AcquisitionResult(kind="waveform", file_type="csv", content="\n".join(rows))

            export = append_result(workbook_path, "USB::TEST", "TEST,DSOX2024A,1,1", result)
            workbook = load_workbook(export.workbook_path)
            sheet = workbook[export.sheet_name]

            self.assertIn("Diagramm-Extrakt: Min/Max", str(sheet["D6"].value))
            self.assertEqual(sheet["D7"].value, "Time")
            self.assertEqual(sheet["E7"].value, "CH1")
            self.assertEqual(sheet["E5"].value, True)
            self.assertTrue(any("B2007" in str(sheet.cell(row, 5).value) for row in range(8, sheet.max_row + 1)))
            self.assertEqual(len(sheet._charts), 1)

    def test_frequency_parsing_and_points(self) -> None:
        self.assertEqual(parse_frequency_hz("100 MHz"), 100_000_000.0)
        self.assertEqual(frequency_points("100 MHz", "102 MHz", "1 MHz"), [100_000_000.0, 101_000_000.0, 102_000_000.0])

    def test_frequency_points_rejects_unbounded_sweeps(self) -> None:
        with self.assertRaises(ValueError):
            frequency_points("1 Hz", f"{MAX_SWEEP_POINTS + 1} Hz", "1 Hz")

    def test_voltage_points(self) -> None:
        self.assertEqual(voltage_points("0 V", "2 V", "1 V"), [0.0, 1.0, 2.0])

    def test_frequency_sweep_sets_generator_and_reads_dmm(self) -> None:
        generator = FakeInstrument(query_responses={
            "*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0",
            ":SOUR:FREQ:CW?": "100000000",
            ":SOUR:POW?": "-30",
            ":OUTP?": "1",
        })
        generator.address = "GPIB0::1::INSTR"
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0", ":READ?": "4.2"})
        measurement.address = "GPIB0::2::INSTR"

        result = run_frequency_sweep(
            generator,  # type: ignore[arg-type]
            measurement,  # type: ignore[arg-type]
            FrequencySweepConfig(
                start_frequency="100 MHz",
                stop_frequency="101 MHz",
                step_frequency="1 MHz",
                power="-30 dBm",
                max_power_dbm=0,
                settle_s=0,
                measurement_mode="dmm",
            ),
        )

        self.assertEqual(result.actual_count, 2)
        self.assertEqual(result.ok_count, 2)
        self.assertIn("SetFrequencyHz,Index", result.csv_content)
        self.assertIn("100000000.000000", result.csv_content)
        self.assertIn("101000000.000000", result.csv_content)
        self.assertEqual(generator.writes[-1], ":OUTP OFF")
        self.assertEqual(measurement.queries, ["*IDN?", ":READ?", ":READ?"])

    def test_custom_sequence_repeats_variable_and_reads_dmm(self) -> None:
        generator = FakeInstrument(query_responses={
            "*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0",
            ":SOUR:FREQ:CW?": "100000000",
            ":SOUR:POW?": "-30",
            ":OUTP?": "1",
        })
        generator.address = "GPIB0::1::INSTR"
        dmm = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0", ":READ?": "4.2"})
        dmm.address = "GPIB0::2::INSTR"

        result = run_custom_sequence(
            {"Generator1": generator, "DMM1": dmm},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Generator1": generator.address, "DMM1": dmm.address},
                steps=[
                    SequenceStep("Generator1", "generator_set_frequency", {"frequency": "${frequency}", "power": "-30 dBm", "max_power_dbm": "0", "rf": "ON"}),
                    SequenceStep("DMM1", "dmm_read"),
                ],
                repeat=2,
                variables=[SequenceVariable("frequency", "100 MHz", "1 MHz", "frequency")],
            ),
        )

        self.assertEqual(result.actual_count, 4)
        self.assertEqual(result.ok_count, 4)
        self.assertIn(":SOUR:FREQ:CW 100000000HZ", generator.writes)
        self.assertIn(":SOUR:FREQ:CW 101000000HZ", generator.writes)
        self.assertEqual(dmm.queries, ["*IDN?", ":READ?", ":READ?"])
        self.assertIn("generator_set_frequency", result.csv_content)

    def test_custom_sequence_can_capture_spectrum_trace_summary(self) -> None:
        analyzer = FakeInstrument(query_responses={"*IDN?": "HEWLETT-PACKARD,8591A,123,1.0", "TRA?": "1,2,3"})
        analyzer.address = "GPIB0::18::INSTR"

        result = run_custom_sequence(
            {"Spectrum1": analyzer},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Spectrum1": analyzer.address},
                steps=[SequenceStep("Spectrum1", "capture_waveform", {"channels": "", "point_mode": "RAW"})],
            ),
        )

        self.assertEqual(result.ok_count, 1)
        self.assertIn("waveform", result.csv_content)
        self.assertEqual(analyzer.queries, ["*IDN?", "TRA?"])

    def test_custom_sequence_exports_screenshot_step_artifact(self) -> None:
        instrument = FakeInstrument(query_responses={"*IDN?": "TEST,DSOX2024A,1,1"}, binary_responses={":DISPLAY:DATA? PNG, COLOR": b"PNGDATA"})
        exports: list[tuple[str, str, str, bytes | str]] = []

        def export_step(device: str, info, result: AcquisitionResult) -> str:
            exports.append((device, info.address, result.file_type, result.content))
            return "Datei: screenshot.png"

        result = run_custom_sequence(
            {"Scope1": instrument},  # type: ignore[dict-item]
            CustomSequenceConfig(devices={"Scope1": instrument.address}, steps=[SequenceStep("Scope1", "capture_screenshot")], end_rf_off=False),
            step_result_export=export_step,
        )

        self.assertEqual(result.ok_count, 1)
        self.assertEqual(exports, [("Scope1", "USB::TEST", "png", b"PNGDATA")])
        self.assertIn("Datei: screenshot.png", result.csv_content)

    def test_custom_sequence_exports_serial_log_step(self) -> None:
        instrument = FakeInstrument(query_responses={"*IDN?": "SERIAL,LOGGER,1,1"})
        instrument.address = "ASRL3::INSTR"
        exports: list[tuple[str, str, str, bytes | str]] = []

        def export_step(device: str, info, result: AcquisitionResult) -> str:
            exports.append((device, info.address, result.file_type, result.content))
            return "Datei: serial-log.txt"

        result = run_custom_sequence(
            {"Serial1": instrument},  # type: ignore[dict-item]
            CustomSequenceConfig(devices={"Serial1": instrument.address}, steps=[SequenceStep("Serial1", "serial_log", {"duration_s": "2.5", "baudrate": "115200", "serial_format": "8N1"})], end_rf_off=False),
            step_result_export=export_step,
        )

        self.assertEqual(result.ok_count, 1)
        self.assertEqual(instrument.serial_log_durations, [2.5])
        self.assertEqual(instrument.serial_log_baudrates, [115200])
        self.assertEqual(exports, [("Serial1", "ASRL3::INSTR", "txt", "serial line 1\nserial line 2")])
        self.assertIn("Datei: serial-log.txt", result.csv_content)
        self.assertNotIn("serial line 1\nserial line 2", result.csv_content)

    def test_custom_sequence_serial_log_device_does_not_require_idn(self) -> None:
        instrument = FakeInstrument()
        instrument.address = "ASRL4::INSTR"

        def failing_query(command: str) -> str:
            raise TimeoutError(command)

        instrument.query = failing_query  # type: ignore[method-assign]

        result = run_custom_sequence(
            {"Serial1": instrument},  # type: ignore[dict-item]
            CustomSequenceConfig(devices={"Serial1": instrument.address}, steps=[SequenceStep("Serial1", "serial_log", {"duration_s": "1", "baudrate": "9600", "serial_format": "8N1"})], end_rf_off=False),
        )

        self.assertEqual(result.ok_count, 1)
        self.assertIn("Serieller Log ohne IDN", result.csv_content)
        self.assertEqual(instrument.serial_log_durations, [1.0])

    def test_read_direct_serial_log_decodes_bytes(self) -> None:
        class FakeSerial:
            def __init__(self, port: str, baudrate: int, bytesize: int, parity: str, stopbits: float, timeout: float) -> None:
                self.port = port
                self.baudrate = baudrate
                self.bytesize = bytesize
                self.parity = parity
                self.stopbits = stopbits
                self.timeout = timeout
                self.reads = [b"boot ", b"ok\n", b""]

            def __enter__(self):
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            @property
            def in_waiting(self) -> int:
                return len(self.reads[0]) if self.reads else 0

            def read(self, size: int) -> bytes:
                if self.reads:
                    return self.reads.pop(0)
                return b""

        import instrument_visa.sequence as sequence_module

        original_serial = sequence_module.serial
        sequence_module.serial = SimpleNamespace(Serial=FakeSerial)  # type: ignore[assignment]
        try:
            result = read_direct_serial_log("COM3", 0.01, 115200, 7, "E", 1)
        finally:
            sequence_module.serial = original_serial  # type: ignore[assignment]

        self.assertEqual(result, "boot ok\n")

    def test_parse_serial_format(self) -> None:
        self.assertEqual(parse_serial_format("8N1"), (8, "N", 1.0))
        self.assertEqual(parse_serial_format("7-E-1"), (7, "E", 1.0))
        self.assertEqual(parse_serial_format("8N1.5"), (8, "N", 1.5))

        with self.assertRaises(ValueError):
            parse_serial_format("9N1")

    def test_parse_parallel_tasks(self) -> None:
        tasks = parse_parallel_tasks("DMM1:dmm; Scope1:scope:Vpp:2; Serial1:serial:9600:8N1")

        self.assertEqual([task.device for task in tasks], ["DMM1", "Scope1", "Serial1"])
        self.assertEqual(tasks[1].measurement, "Vpp")
        self.assertEqual(tasks[1].channel, 2)
        self.assertEqual(tasks[2].baudrate, 9600)

    def test_custom_sequence_parallel_phase_runs_measurements(self) -> None:
        dmm = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0", ":READ?": "4.2"})
        dmm.address = "GPIB0::2::INSTR"
        scope = FakeInstrument(query_responses={"*IDN?": "TEST,DSOX2024A,1,1", ":MEASure:VPP? CHANnel1": "1.1"})
        scope.address = "USB::SCOPE"
        exports: list[tuple[str, str, str]] = []

        def export_step(device: str, info, result: AcquisitionResult) -> str:
            exports.append((device, info.address, result.file_type))
            return "Tabellenblatt: parallel"

        result = run_custom_sequence(
            {"DMM1": dmm, "Scope1": scope},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"DMM1": dmm.address, "Scope1": scope.address},
                steps=[SequenceStep("", "parallel_phase", {"duration_s": "0.01", "interval_s": "0.01", "tasks": "DMM1:dmm; Scope1:scope:Vpp:1"})],
                end_rf_off=False,
            ),
            step_result_export=export_step,
        )

        self.assertEqual(result.ok_count, 1)
        self.assertIn("parallel phase", result.csv_content)
        self.assertEqual(exports[0][2], "csv")

    def test_append_result_writes_serial_log_text_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "results.xlsx"
            export = append_result(workbook_path, "ASRL3::INSTR", "Serieller Log", AcquisitionResult(kind="serial log", file_type="txt", content="line 1\nline 2"))

            self.assertTrue(workbook_path.exists())
            self.assertIsNotNone(export.artifact_path)
            self.assertEqual(export.artifact_path.read_text(encoding="utf-8"), "line 1\nline 2")

    def test_picoscope_channel_parsers(self) -> None:
        self.assertEqual(parse_pico_analog_channels("A,B,CHC"), ["A", "B", "C"])
        self.assertEqual(parse_pico_digital_channels("D0-D3,D7"), [0, 1, 2, 3, 7])

        with self.assertRaises(ValueError):
            parse_pico_analog_channels("Z")
        with self.assertRaises(ValueError):
            parse_pico_digital_channels("D16")

    def test_custom_sequence_picoscope_analog_step(self) -> None:
        pico = FakeInstrument(query_responses={"*IDN?": "PicoScope 2000A"})
        pico.address = "PICO2000A::AUTO"
        exports: list[tuple[str, str]] = []

        def export_step(device: str, info, result: AcquisitionResult) -> str:
            exports.append((device, result.file_type))
            return "Tabellenblatt: PicoAnalog"

        result = run_custom_sequence(
            {"Pico1": pico},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Pico1": pico.address},
                steps=[SequenceStep("Pico1", "picoscope_analog", {"channels": "A,B", "range": "5V", "samples": "100", "interval_us": "2"})],
                end_rf_off=False,
            ),
            step_result_export=export_step,
        )

        self.assertEqual(result.ok_count, 1)
        self.assertEqual(pico.pico_analog_configs[0].channels, "A,B")
        self.assertEqual(exports, [("Pico1", "csv")])

    def test_custom_sequence_picoscope_digital_step(self) -> None:
        pico = FakeInstrument(query_responses={"*IDN?": "PicoScope 2000A"})
        pico.address = "PICO2000A::AUTO"

        result = run_custom_sequence(
            {"Pico1": pico},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Pico1": pico.address},
                steps=[SequenceStep("Pico1", "picoscope_digital", {"channels": "D0-D7", "logic_level_mv": "1500", "samples": "100", "interval_us": "2"})],
                end_rf_off=False,
            ),
        )

        self.assertEqual(result.ok_count, 1)
        self.assertEqual(pico.pico_digital_configs[0].channels, "D0-D7")

    def test_parse_34970a_channels(self) -> None:
        self.assertEqual(parse_34970a_channels("1-3,5"), [1, 2, 3, 5])

        with self.assertRaises(ValueError):
            parse_34970a_channels("0")
        with self.assertRaises(ValueError):
            parse_34970a_channels("23")

    def test_34970a_voltage_read_uses_channel_list(self) -> None:
        instrument = FakeInstrument(query_responses={"MEAS:VOLT:DC? (@101,102,103)": "1.0,2.0,3.0"})

        result = read_34970a_data_logger(instrument, DataLogger34970AConfig(measurement="VOLT_DC", channels="1-3"))

        self.assertEqual(result.file_type, "csv")
        self.assertIn("101", instrument.queries[0])
        self.assertIn("1,VOLT_DC,1.0,V", str(result.content))

    def test_34970a_temperature_read_sets_serial_and_tc_type(self) -> None:
        instrument = FakeInstrument(query_responses={"MEAS:TEMP? TC,K,(@101)": "23.5"})

        result = read_34970a_data_logger(instrument, DataLogger34970AConfig(measurement="TEMP", channels="1", thermocouple_type="K", baudrate=19200, serial_format="7E1"))

        self.assertIn("1,TEMP,23.5,degC", str(result.content))
        self.assertEqual(instrument.serial_configs, [(19200, 7, "E", 1.0)])

    def test_parse_34970a_measurement_plan(self) -> None:
        tasks = parse_34970a_measurement_plan("1-4:VOLT_DC; 5:TEMP; 6-7:RES")

        self.assertEqual([(task.channels, task.measurement) for task in tasks], [("1-4", "VOLT_DC"), ("5", "TEMP"), ("6-7", "RES")])

        with self.assertRaises(ValueError):
            parse_34970a_measurement_plan("1-4")

    def test_custom_sequence_34970a_step(self) -> None:
        instrument = FakeInstrument(query_responses={"*IDN?": "HEWLETT-PACKARD,34970A,0,1", "MEAS:RES? (@101,102)": "10,20"})
        instrument.address = "COM5"

        result = run_custom_sequence(
            {"Logger1": instrument},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Logger1": instrument.address},
                steps=[SequenceStep("Logger1", "data_logger_34970a_read", {"measurement": "RES", "channels": "1-2", "range": "AUTO", "resolution": "DEF", "thermocouple_type": "K", "baudrate": "9600", "serial_format": "8N1"})],
                end_rf_off=False,
            ),
        )

        self.assertEqual(result.ok_count, 1)
        self.assertIn("34970A data logger", result.csv_content)

    def test_custom_sequence_34970a_measurement_plan_step(self) -> None:
        instrument = FakeInstrument(
            query_responses={
                "*IDN?": "HEWLETT-PACKARD,34970A,0,1",
                "MEAS:VOLT:DC? (@101,102)": "1,2",
                "MEAS:TEMP? TC,K,(@103)": "23",
            }
        )

        result = run_custom_sequence(
            {"Logger1": instrument},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Logger1": "COM5"},
                steps=[SequenceStep("Logger1", "data_logger_34970a_plan", {"plan": "1-2:VOLT_DC; 3:TEMP", "baudrate": "9600", "serial_format": "8N1"})],
                end_rf_off=False,
            ),
        )

        self.assertEqual(result.ok_count, 1)
        self.assertIn("34970A measurement plan", result.csv_content)

    def test_custom_sequence_power_supply_uses_configured_safety_limits(self) -> None:
        supply = FakeInstrument(query_responses={"*IDN?": "HAMEG,HMP4030,123,1.0"})

        result = run_custom_sequence(
            {"Supply1": supply},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Supply1": supply.address},
                steps=[SequenceStep("Supply1", "power_supply_set", {"voltage": "10 V", "current": "0.1 A", "channel": "1", "output": "ON"})],
                power_supply_max_voltage=5,
                power_supply_max_current=1,
            )
        )

        self.assertEqual(result.error_count, 1)
        self.assertIn("exceeds max voltage", result.csv_content)
        self.assertEqual(supply.writes, [])

    def test_custom_sequence_validation_rejects_bad_imported_step(self) -> None:
        instrument = FakeInstrument(query_responses={"*IDN?": "TEST,UNKNOWN,1,1"})

        with self.assertRaises(ValueError):
            run_custom_sequence(
                {"Device1": instrument},  # type: ignore[dict-item]
                CustomSequenceConfig(devices={"Device1": instrument.address}, steps=[SequenceStep("Device1", "unknown_action")]),
            )

    def test_cli_loads_json_sequence_config(self) -> None:
        content = {
            "devices": {"DMM1": "GPIB0::2::INSTR"},
            "repeat": 2,
            "pause_s": 0,
            "variables": [{"name": "value", "start": "0", "step": "1", "unit": "number"}],
            "steps": [{"device": "DMM1", "action": "dmm_read", "params": {}}],
            "end_rf_off": False,
            "end_power_supply_off": False,
            "power_supply_max_voltage": 5,
            "power_supply_max_current": 1,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            sequence_path = Path(temp_dir) / "ablauf.json"
            sequence_path.write_text(__import__("json").dumps(content), encoding="utf-8")

            config = _load_sequence_config(sequence_path)

        self.assertEqual(config.devices, {"DMM1": "GPIB0::2::INSTR"})
        self.assertEqual(config.repeat, 2)
        self.assertEqual(config.steps, [SequenceStep("DMM1", "dmm_read", {})])
        self.assertEqual(config.variables[0].name, "value")
        self.assertFalse(config.end_rf_off)

    def test_cli_sequence_config_parses_boolean_strings(self) -> None:
        content = {
            "devices": {"DMM1": "GPIB0::2::INSTR"},
            "steps": [{"device": "DMM1", "action": "dmm_read", "params": {}}],
            "end_rf_off": "false",
            "end_power_supply_off": "true",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            sequence_path = Path(temp_dir) / "ablauf.json"
            sequence_path.write_text(__import__("json").dumps(content), encoding="utf-8")

            config = _load_sequence_config(sequence_path)

        self.assertFalse(config.end_rf_off)
        self.assertTrue(config.end_power_supply_off)

    def test_cli_sequence_config_rejects_invalid_boolean_strings(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_bool("maybe", True)

    def test_custom_sequence_stops_on_step_error_and_cleans_up_generator(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0", ":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "1"})

        def failing_write(command: str) -> None:
            if command == ":SOUR:FREQ:CW 100 MHz":
                raise RuntimeError("generator failed")
            generator.writes.append(command)

        generator.write = failing_write  # type: ignore[method-assign]
        result = run_custom_sequence(
            {"Generator1": generator},  # type: ignore[dict-item]
            CustomSequenceConfig(
                devices={"Generator1": generator.address},
                steps=[SequenceStep("Generator1", "generator_set_frequency", {"frequency": "100 MHz", "power": "-30 dBm", "max_power_dbm": "0"})],
            ),
        )

        self.assertEqual(result.error_count, 1)
        self.assertIn(":OUTP OFF", generator.writes)
        self.assertIn("generator failed", result.csv_content)

    def test_frequency_sweep_rejects_power_above_limit_before_writes(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0"})
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0"})

        with self.assertRaises(ValueError):
            run_frequency_sweep(
                generator,  # type: ignore[arg-type]
                measurement,  # type: ignore[arg-type]
                FrequencySweepConfig(
                    start_frequency="100 MHz",
                    stop_frequency="101 MHz",
                    step_frequency="1 MHz",
                    power="10 dBm",
                    max_power_dbm=0,
                    settle_s=0,
                    measurement_mode="dmm",
                ),
            )

        self.assertEqual(generator.writes, [])

    def test_frequency_sweep_can_stop_before_first_point(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0", ":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "0"})
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0"})

        result = run_frequency_sweep(
            generator,  # type: ignore[arg-type]
            measurement,  # type: ignore[arg-type]
            FrequencySweepConfig("100 MHz", "101 MHz", "1 MHz", "-30 dBm", 0, 0, "dmm"),
            stop_requested=lambda: True,
        )

        self.assertEqual(result.actual_count, 0)
        self.assertTrue(result.stopped)
        self.assertIn("StoppedByUser,Yes", result.csv_content)

    def test_frequency_sweep_stop_turns_rf_off_even_when_end_off_disabled(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0", ":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "1"})
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0"})
        calls = {"count": 0}

        def stop_after_generator_set() -> bool:
            calls["count"] += 1
            return calls["count"] >= 2

        result = run_frequency_sweep(
            generator,  # type: ignore[arg-type]
            measurement,  # type: ignore[arg-type]
            FrequencySweepConfig("100 MHz", "101 MHz", "1 MHz", "-30 dBm", 0, 0, "dmm", rf_off_at_end=False),
            stop_requested=stop_after_generator_set,
        )

        self.assertTrue(result.stopped)
        self.assertEqual(generator.writes[-1], ":OUTP OFF")

    def test_frequency_sweep_aborts_on_generator_error_and_turns_rf_off(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0", ":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "1"})
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0", ":READ?": "4.2"})
        original_write = generator.write

        def failing_write(command: str) -> None:
            if command == ":SOUR:FREQ:CW 100000000HZ":
                raise RuntimeError("generator failed")
            original_write(command)

        generator.write = failing_write  # type: ignore[method-assign]
        result = run_frequency_sweep(
            generator,  # type: ignore[arg-type]
            measurement,  # type: ignore[arg-type]
            FrequencySweepConfig("100 MHz", "101 MHz", "1 MHz", "-30 dBm", 0, 0, "dmm"),
        )

        self.assertEqual(result.actual_count, 1)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(measurement.queries, ["*IDN?"])
        self.assertIn(":OUTP OFF", generator.writes)

    def test_frequency_sweep_export_charts_only_value(self) -> None:
        from openpyxl import load_workbook

        content = "SetFrequencyHz,Index,ElapsedSeconds,Value,Status\n100000000,1,0.1,4.2,OK\n101000000,2,0.2,4.4,OK\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "results.xlsx"
            export = append_result(workbook_path, "GPIB0::1::INSTR", "Rohde&Schwarz,SMIQ03B,123,1.0", AcquisitionResult("frequency sweep", "csv", content))
            workbook = load_workbook(workbook_path)
            sheet = workbook[export.sheet_name]

            self.assertEqual(len(sheet._charts), 1)
            self.assertEqual(len(sheet._charts[0].series), 1)

    def test_voltage_sweep_sets_power_supply_and_reads_dmm(self) -> None:
        supply = FakeInstrument(
            query_responses={
                "*IDN?": "HAMEG,HMP4030,123,1.0",
                "VOLT?": "1.000",
                "CURR?": "0.100",
                "MEAS:VOLT?": "1.000",
                "MEAS:CURR?": "0.010",
                "OUTP:SEL?": "1",
                "OUTP:GEN?": "1",
            }
        )
        supply.address = "GPIB0::3::INSTR"
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0", ":READ?": "0.5"})
        measurement.address = "GPIB0::2::INSTR"

        result = run_voltage_sweep(
            supply,  # type: ignore[arg-type]
            measurement,  # type: ignore[arg-type]
            VoltageSweepConfig(
                start_voltage="0 V",
                stop_voltage="1 V",
                step_voltage="1 V",
                current_limit="0.1 A",
                channel=1,
                max_voltage=5,
                max_current=1,
                settle_s=0,
                measurement_mode="dmm",
            ),
        )

        self.assertEqual(result.actual_count, 2)
        self.assertEqual(result.ok_count, 2)
        self.assertIn("SetVoltageV,Index", result.csv_content)
        self.assertIn("SupplyVoltageMeasured", result.csv_content)
        self.assertIn("SupplyCurrentMeasured", result.csv_content)
        self.assertIn("0.000000", result.csv_content)
        self.assertIn("1.000000", result.csv_content)
        self.assertEqual(supply.writes[-2:], ["OUTP:GEN 0", "INST:NSEL 1"])
        self.assertEqual(measurement.queries, ["*IDN?", ":READ?", ":READ?"])

    def test_timed_switch_generator_toggles_rf_and_ends_off(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0", ":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "0"})
        generator.address = "GPIB0::1::INSTR"

        result = run_timed_switch(
            generator,  # type: ignore[arg-type]
            TimedSwitchConfig(source_type="generator", on_s=0.001, off_s=0, repetitions=2, end_off=True),
        )

        self.assertEqual(result.actual_count, 4)
        self.assertEqual(result.ok_count, 4)
        self.assertEqual(generator.writes, [":OUTP ON", ":OUTP OFF", ":OUTP ON", ":OUTP OFF", ":OUTP OFF"])
        self.assertIn("SourceType", result.csv_content)

    def test_timed_switch_power_supply_channel_mode(self) -> None:
        supply = FakeInstrument(
            query_responses={
                "*IDN?": "HAMEG,HMP4030,123,1.0",
                "VOLT?": "1.000",
                "CURR?": "0.100",
                "MEAS:VOLT?": "1.000",
                "MEAS:CURR?": "0.010",
                "OUTP:SEL?": "0",
                "OUTP:GEN?": "1",
            }
        )

        result = run_timed_switch(
            supply,  # type: ignore[arg-type]
            TimedSwitchConfig(source_type="power_supply", on_s=0.001, off_s=0, repetitions=1, power_supply_channel=2, power_supply_switch_mode="channel"),
        )

        self.assertEqual(result.actual_count, 2)
        self.assertEqual(supply.writes[:3], ["INST:NSEL 2", "INST:NSEL 2", "OUTP:SEL 1"])
        self.assertIn("OUTP:SEL 0", supply.writes)

    def test_timed_switch_rejects_generator_power_above_limit_before_writes(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0"})

        with self.assertRaises(ValueError):
            run_timed_switch(
                generator,  # type: ignore[arg-type]
                TimedSwitchConfig(source_type="generator", on_s=1, off_s=1, repetitions=1, generator_power="10 dBm", generator_max_power_dbm=0),
            )

        self.assertEqual(generator.writes, [])

    def test_timed_switch_rejects_current_generator_power_without_setup(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0", ":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "10", ":OUTP?": "0"})

        with self.assertRaises(ValueError):
            run_timed_switch(
                generator,  # type: ignore[arg-type]
                TimedSwitchConfig(source_type="generator", on_s=1, off_s=1, repetitions=1, generator_power="-30 dBm", generator_max_power_dbm=0, setup_before_start=False),
            )

        self.assertEqual(generator.writes, [":OUTP OFF"])

    def test_frequency_sweep_records_final_off_failure(self) -> None:
        generator = FakeInstrument(query_responses={"*IDN?": "Rohde&Schwarz,SMIQ03B,123,1.0", ":SOUR:FREQ:CW?": "100000000", ":SOUR:POW?": "-30", ":OUTP?": "1"})
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0"})

        def failing_write(command: str) -> None:
            if command == ":OUTP OFF":
                raise RuntimeError("off failed")
            generator.writes.append(command)

        generator.write = failing_write  # type: ignore[method-assign]
        result = run_frequency_sweep(
            generator,  # type: ignore[arg-type]
            measurement,  # type: ignore[arg-type]
            FrequencySweepConfig("100 MHz", "100 MHz", "1 MHz", "-30 dBm", 0, 0, "dmm"),
            stop_requested=lambda: True,
        )

        self.assertEqual(result.error_count, 1)
        self.assertIn("FINAL_OFF_ERROR", result.csv_content)

    def test_voltage_sweep_rejects_voltage_above_limit_before_writes(self) -> None:
        supply = FakeInstrument(query_responses={"*IDN?": "HAMEG,HMP4030,123,1.0"})
        measurement = FakeInstrument(query_responses={"*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2000,123,1.0"})

        with self.assertRaises(ValueError):
            run_voltage_sweep(
                supply,  # type: ignore[arg-type]
                measurement,  # type: ignore[arg-type]
                VoltageSweepConfig("0 V", "10 V", "1 V", "0.1 A", 1, 5, 1, 0, "dmm"),
            )

        self.assertEqual(supply.writes, [])

    def test_voltage_sweep_export_charts_only_value(self) -> None:
        from openpyxl import load_workbook

        content = "SetVoltageV,Index,ElapsedSeconds,Value,Status\n0,1,0.1,4.2,OK\n1,2,0.2,4.4,OK\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "results.xlsx"
            export = append_result(workbook_path, "GPIB0::3::INSTR", "HAMEG,HMP4030,123,1.0", AcquisitionResult("voltage sweep", "csv", content))
            workbook = load_workbook(workbook_path)
            sheet = workbook[export.sheet_name]

            self.assertEqual(len(sheet._charts), 1)
            self.assertEqual(len(sheet._charts[0].series), 1)


if __name__ == "__main__":
    unittest.main()
