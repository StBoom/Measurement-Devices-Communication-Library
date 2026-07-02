from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from instrument_visa.acquisition import (  # noqa: E402
    AcquisitionResult,
    capture_screenshot,
    capture_waveform,
    read_signal_generator_settings,
    read_scope_measurement,
    read_value,
    set_signal_generator,
    set_signal_generator_rf_output,
)
from instrument_visa.excel_export import append_result  # noqa: E402
from instrument_visa.profiles import detect_profile  # noqa: E402


class FakeInstrument:
    def __init__(self, query_responses: dict[str, str] | None = None, binary_responses: dict[str, bytes] | None = None) -> None:
        self.query_responses = query_responses or {}
        self.binary_responses = binary_responses or {}
        self.raw_responses: dict[str, bytes] = {}
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.binary_queries: list[str] = []
        self.raw_writes: list[str] = []

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


if __name__ == "__main__":
    unittest.main()
