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
    read_scope_measurement,
    read_value,
)
from instrument_visa.excel_export import append_result  # noqa: E402
from instrument_visa.profiles import detect_profile  # noqa: E402


class FakeInstrument:
    def __init__(self, query_responses: dict[str, str] | None = None, binary_responses: dict[str, bytes] | None = None) -> None:
        self.query_responses = query_responses or {}
        self.binary_responses = binary_responses or {}
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.binary_queries: list[str] = []

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        return self.query_responses.get(command, "1.23")

    def query_binary(self, command: str) -> bytes:
        self.binary_queries.append(command)
        return self.binary_responses.get(command, b"DATA")


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
