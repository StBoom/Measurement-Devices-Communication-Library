from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from math import ceil
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.chart import LineChart, Reference, ScatterChart, Series
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .acquisition import AcquisitionResult


MAX_CHART_POINTS = 2000


@dataclass(frozen=True)
class ExportResult:
    workbook_path: Path
    artifact_path: Path | None = None
    sheet_name: str | None = None


def append_result(workbook_path: Path, address: str, idn: str, result: AcquisitionResult) -> ExportResult:
    artifact: Path | None = None
    result_sheet_name: str | None = None
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    if workbook_path.exists():
        try:
            workbook = load_workbook(workbook_path)
        except (BadZipFile, KeyError):
            workbook_path = _backup_corrupt_workbook(workbook_path)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Results"
            _initialize_results_sheet(sheet)
        else:
            sheet = workbook.active
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Results"
        _initialize_results_sheet(sheet)

    if isinstance(result.content, bytes):
        artifact = _artifact_path(workbook_path, result.file_type)
        artifact.write_bytes(result.content)
        image_sheet_name = _add_image_sheet(workbook, timestamp, address, idn, result, artifact)
        result_sheet_name = image_sheet_name
        target = f"sheet:{image_sheet_name}" if image_sheet_name else str(artifact)
        sheet.append([timestamp, address, idn, result.kind, result.file_type, target])
    elif result.file_type == "csv":
        data_sheet = workbook.create_sheet(_unique_sheet_name(workbook, result.kind))
        result_sheet_name = data_sheet.title
        sheet.append([timestamp, address, idn, result.kind, result.file_type, f"sheet:{result_sheet_name}"])
        data_sheet.append(["Timestamp", timestamp])
        data_sheet.append(["Address", address])
        data_sheet.append(["IDN", idn])
        data_sheet.append(["Kind", result.kind])
        data_sheet.append(["FileType", result.file_type])
        data_sheet.append([])
        _append_csv(data_sheet, result.content)
        if result.kind == "waveform":
            _add_waveform_chart(data_sheet)
        _format_sheet(data_sheet)
    elif result.file_type.startswith("s") and result.file_type.endswith("p"):
        artifact = _artifact_path(workbook_path, result.file_type)
        artifact.write_text(result.content, encoding="utf-8")
        sheet.append([timestamp, address, idn, result.kind, result.file_type, str(artifact)])
    else:
        sheet.append([timestamp, address, idn, result.kind, result.file_type, result.content])

    _format_sheet(sheet)
    workbook.save(workbook_path)
    return ExportResult(workbook_path=workbook_path, artifact_path=artifact, sheet_name=result_sheet_name)


def _append_csv(sheet, content: str) -> None:
    for row in csv.reader(StringIO(content)):
        sheet.append([_coerce_excel_value(value) for value in row])


def _coerce_excel_value(value: str) -> str | float:
    value = value.strip()
    if not value:
        return ""
    try:
        return float(value)
    except ValueError:
        return value


def _initialize_results_sheet(sheet) -> None:
    sheet.append(["Timestamp", "Address", "IDN", "Kind", "FileType", "ValueOrFile"])


def _artifact_path(workbook_path: Path, file_type: str) -> Path:
    return workbook_path.with_name(f"{workbook_path.stem}-{uuid4().hex[:8]}.{file_type}")


def _add_image_sheet(workbook, timestamp: str, address: str, idn: str, result: AcquisitionResult, artifact: Path) -> str | None:
    if result.file_type.lower() not in {"png", "jpg", "jpeg"}:
        return None

    image_sheet = workbook.create_sheet(_unique_sheet_name(workbook, result.kind))
    image_sheet.append(["Timestamp", timestamp])
    image_sheet.append(["Address", address])
    image_sheet.append(["IDN", idn])
    image_sheet.append(["Kind", result.kind])
    image_sheet.append(["ImageFile", str(artifact)])
    image_sheet.append([])
    try:
        image = ExcelImage(str(artifact))
        image.anchor = "A7"
        image_sheet.add_image(image)
    except Exception as exc:
        image_sheet.append(["ImageEmbedError", str(exc)])
    _format_sheet(image_sheet)
    return image_sheet.title


def _add_waveform_chart(sheet) -> None:
    header_row = _find_waveform_header_row(sheet)
    if header_row is None:
        return

    scan_max_row = min(sheet.max_row, header_row + MAX_CHART_POINTS)
    numeric_columns = _numeric_columns(sheet, header_row, scan_max_row)
    if not numeric_columns:
        return

    header_values = [sheet.cell(header_row, column).value for column in range(1, sheet.max_column + 1)]
    first_header = str(header_values[0]).strip().lower() if header_values and header_values[0] is not None else ""
    has_x_axis = 1 in numeric_columns and first_header in {"time", "frequency", "freq", "[hz]", "hz"}
    max_row = _last_numeric_row(sheet, header_row + 1, numeric_columns)
    if max_row <= header_row:
        return

    anchor = _chart_anchor(sheet)
    if max_row - header_row > MAX_CHART_POINTS:
        header_row, max_row, numeric_columns, anchor = _add_sampled_chart_table(sheet, header_row, max_row, numeric_columns, has_x_axis)

    if has_x_axis and len(numeric_columns) > 1:
        _add_scatter_waveform_chart(sheet, header_row, max_row, numeric_columns, anchor)
    else:
        _add_line_waveform_chart(sheet, header_row, max_row, numeric_columns, anchor)


def _find_waveform_header_row(sheet) -> int | None:
    for row in range(1, sheet.max_row + 1):
        values = [sheet.cell(row, column).value for column in range(1, sheet.max_column + 1)]
        normalized = {str(value).strip().lower() for value in values if value is not None}
        if normalized & {"time", "frequency", "trace", "[hz]", "hz", "ch1", "channel1"}:
            return row
    return None


def _last_numeric_row(sheet, first_data_row: int, numeric_columns: list[int]) -> int:
    for row in range(sheet.max_row, first_data_row - 1, -1):
        if any(isinstance(sheet.cell(row, column).value, (int, float)) for column in numeric_columns):
            return row
    return first_data_row - 1


def _numeric_columns(sheet, header_row: int, max_row: int) -> list[int]:
    columns: list[int] = []
    for column in range(1, sheet.max_column + 1):
        if any(isinstance(sheet.cell(row, column).value, (int, float)) for row in range(header_row + 1, max_row + 1)):
            columns.append(column)
    return columns


def _add_sampled_chart_table(sheet, source_header_row: int, source_max_row: int, source_numeric_columns: list[int], has_x_axis: bool) -> tuple[int, int, list[int], str]:
    source_columns = [1, *[column for column in source_numeric_columns if column != 1]] if has_x_axis else source_numeric_columns
    start_column = sheet.max_column + 2
    note_row = max(1, source_header_row - 1)
    sample_header_row = source_header_row if source_header_row > 1 else 2
    sample_data_row = sample_header_row + 1
    step = max(1, ceil((source_max_row - source_header_row) / MAX_CHART_POINTS))

    sheet.cell(note_row, start_column).value = f"Diagramm-Extrakt: jeder {step}. Punkt plus letzter Punkt; vollständige Daten links."

    for offset, source_column in enumerate(source_columns):
        sheet.cell(sample_header_row, start_column + offset).value = sheet.cell(source_header_row, source_column).value or f"Column {source_column}"

    last_copied_source_row = 0
    for source_row in range(source_header_row + 1, source_max_row + 1, step):
        if not any(isinstance(sheet.cell(source_row, column).value, (int, float)) for column in source_numeric_columns):
            continue
        _copy_sampled_row(sheet, source_row, sample_data_row, source_columns, start_column)
        last_copied_source_row = source_row
        sample_data_row += 1

    if last_copied_source_row != source_max_row:
        _copy_sampled_row(sheet, source_max_row, sample_data_row, source_columns, start_column)
        sample_data_row += 1

    sample_columns = list(range(start_column, start_column + len(source_columns)))
    anchor = f"{get_column_letter(start_column + len(source_columns) + 2)}{source_header_row}"
    return sample_header_row, sample_data_row - 1, sample_columns, anchor


def _copy_sampled_row(sheet, source_row: int, sample_row: int, source_columns: list[int], start_column: int) -> None:
    for offset, source_column in enumerate(source_columns):
        sheet.cell(sample_row, start_column + offset).value = sheet.cell(source_row, source_column).value


def _add_scatter_waveform_chart(sheet, header_row: int, max_row: int, numeric_columns: list[int], anchor: str) -> None:
    chart = ScatterChart()
    chart.title = "Waveform"
    x_column = numeric_columns[0]
    chart.x_axis.title = str(sheet.cell(header_row, x_column).value or "X")
    chart.y_axis.title = "Value"
    chart.legend.position = "r"

    x_values = Reference(sheet, min_col=x_column, min_row=header_row + 1, max_row=max_row)
    for column in numeric_columns:
        if column == x_column:
            continue
        y_values = Reference(sheet, min_col=column, min_row=header_row + 1, max_row=max_row)
        series = Series(y_values, x_values, title=str(sheet.cell(header_row, column).value or f"Series {column}"))
        chart.series.append(series)

    if chart.series:
        sheet.add_chart(chart, anchor)


def _add_line_waveform_chart(sheet, header_row: int, max_row: int, numeric_columns: list[int], anchor: str) -> None:
    chart = LineChart()
    chart.title = "Waveform"
    chart.x_axis.title = "Point"
    chart.y_axis.title = "Value"
    chart.legend.position = "r"

    data = Reference(sheet, min_col=min(numeric_columns), max_col=max(numeric_columns), min_row=header_row, max_row=max_row)
    chart.add_data(data, titles_from_data=True)
    sheet.add_chart(chart, anchor)


def _chart_anchor(sheet) -> str:
    return f"{get_column_letter(min(sheet.max_column + 2, 12))}7"


def _unique_sheet_name(workbook, kind: str) -> str:
    prefix = "".join(character for character in kind.title() if character.isalnum())[:16] or "Result"
    timestamp = datetime.now().strftime("%H%M%S")
    base_name = f"{prefix}-{timestamp}"[:31]
    sheet_name = base_name
    counter = 1
    while sheet_name in workbook.sheetnames:
        suffix = f"-{counter}"
        sheet_name = f"{base_name[:31 - len(suffix)]}{suffix}"
        counter += 1
    return sheet_name


def _backup_corrupt_workbook(workbook_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = workbook_path.with_name(f"{workbook_path.stem}.corrupt-{timestamp}{workbook_path.suffix}")
    workbook_path.replace(backup_path)
    return workbook_path


def _format_sheet(sheet) -> None:
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for column_cells in sheet.columns:
        column_letter = get_column_letter(column_cells[0].column)
        max_length = 0
        for cell in column_cells[:200]:
            if cell.value is None:
                continue
            max_length = max(max_length, len(str(cell.value)))
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 60)
