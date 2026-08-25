import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thing_transfer_batch.clickhouse import rows_to_tsv


def test_rows_to_tsv_basic():
    rows = [{"a": "x", "b": 1}, {"a": "y", "b": 2}]
    assert rows_to_tsv(rows, ["a", "b"]) == "x\t1\ny\t2\n"


def test_rows_to_tsv_escapes_tabs_and_newlines():
    rows = [{"a": "has\ttab", "b": "has\nnewline"}]
    tsv = rows_to_tsv(rows, ["a", "b"])
    assert tsv == "has\\ttab\thas\\nnewline\n"


def test_rows_to_tsv_escapes_backslash():
    rows = [{"a": "back\\slash"}]
    assert rows_to_tsv(rows, ["a"]) == "back\\\\slash\n"


def test_rows_to_tsv_empty_rows():
    assert rows_to_tsv([], ["a", "b"]) == "\n"
