"""Tests for app.recipients.csv_importer -- content-based column
detection (no header parsing, no manual column mapping UI), name-column
detection, delimiter sniffing, dedup, and the corrupted/unreadable-file
error path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.recipients.csv_importer import CsvImportError, import_recipients_from_csv


def _write_csv(tmp_path: Path, content: str, name: str = "recipients.csv") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8-sig")
    return path


def test_identifier_and_name_columns_detected_regardless_of_order(tmp_path):
    path = _write_csv(tmp_path, "Ivan,@ivan_test\nMaria,@maria_test\n")
    result = import_recipients_from_csv(path)
    assert len(result.valid_recipients) == 2
    keys = {p.normalized_key for p in result.valid_recipients}
    assert result.names == {f"username:ivan_test": "Ivan", "username:maria_test": "Maria"}
    assert keys == set(result.names.keys())


def test_identifier_first_then_name_also_detected(tmp_path):
    path = _write_csv(tmp_path, "@ivan_test,Ivan\n123456789,Maria\n")
    result = import_recipients_from_csv(path)
    assert len(result.valid_recipients) == 2
    assert result.names["username:ivan_test"] == "Ivan"
    assert result.names["id:123456789"] == "Maria"


def test_row_without_any_identifier_is_reported_invalid(tmp_path):
    path = _write_csv(tmp_path, "header1,header2\nJust some text,another column\n")
    result = import_recipients_from_csv(path)
    assert result.invalid_count == 2
    assert len(result.valid_recipients) == 0
    for row in result.parsed:
        assert row.is_valid is False
        assert row.error


def test_semicolon_delimiter_is_sniffed(tmp_path):
    path = _write_csv(tmp_path, "Ivan;@ivan_test\nMaria;@maria_test\n")
    result = import_recipients_from_csv(path)
    assert len(result.valid_recipients) == 2
    assert result.names["username:ivan_test"] == "Ivan"


def test_duplicate_identifiers_are_deduped(tmp_path):
    path = _write_csv(tmp_path, "Ivan,@ivan_test\nIvan again,@ivan_test\n")
    result = import_recipients_from_csv(path)
    assert len(result.valid_recipients) == 1
    assert result.duplicates_removed == 1


def test_second_identifier_like_cell_is_neither_name_nor_second_recipient(tmp_path):
    # Two cells that both look like recipient identifiers in one row --
    # the first wins as the identifier, the second is dropped rather than
    # being misread as a display name.
    path = _write_csv(tmp_path, "@ivan_test,123456789\n")
    result = import_recipients_from_csv(path)
    assert len(result.valid_recipients) == 1
    assert result.valid_recipients[0].value == "ivan_test"
    assert result.names == {}


def test_blank_rows_are_skipped(tmp_path):
    path = _write_csv(tmp_path, "Ivan,@ivan_test\n\n,,\nMaria,@maria_test\n")
    result = import_recipients_from_csv(path)
    assert result.total_rows == 2
    assert len(result.valid_recipients) == 2


def test_single_column_csv_with_no_name(tmp_path):
    path = _write_csv(tmp_path, "@ivan_test\n@maria_test\n")
    result = import_recipients_from_csv(path)
    assert len(result.valid_recipients) == 2
    assert result.names == {}


def test_unreadable_file_raises_csv_import_error(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    with pytest.raises(CsvImportError):
        import_recipients_from_csv(missing)
