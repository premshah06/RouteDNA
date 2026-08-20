import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "gen" / "python"))

import pytest

from catalog import Catalog
from packagepb.v1 import item_pb2


@pytest.fixture
def catalog():
    cat = Catalog()
    yield cat
    cat.close()


def test_sample_item_ids_returns_requested_count(catalog):
    ids = catalog.sample_item_ids(10)
    assert len(ids) == 10
    assert len(set(ids)) == 10  # no duplicates from a 50k-item pool


def test_get_returns_populated_item(catalog):
    [item_id] = catalog.sample_item_ids(1)
    item = catalog.get(item_id)
    assert item is not None
    assert item.item_id == item_id
    assert item.name
    assert item.sku
    assert item.category != item_pb2.ITEM_CATEGORY_UNSPECIFIED
    assert item.unit_weight_kg > 0
    assert item.stock_quantity >= 0


def test_get_unknown_item_id_returns_none(catalog):
    assert catalog.get("not-a-real-item-id") is None


def test_missing_db_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="seed_catalog.py"):
        Catalog(db_path=tmp_path / "nonexistent.db")
